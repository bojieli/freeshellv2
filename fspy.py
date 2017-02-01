#!/bin/env python3
import argparse
import subprocess
import logging
import os
import errno
import base64

logger = logging.getLogger('freeshell log')
logger.setLevel(logging.DEBUG)
VERSION = 0.1


# from http://stackoverflow.com/questions/1158076/implement-touch-using-python
def touch(path):
    with open(path, 'a'):
        os.utime(path, None)


# from http://stackoverflow.com/questions/10840533/most-pythonic-way-to-delete-a-file-which-may-not-exist
def silentremove(filename):
    try:
        os.remove(filename)
    except OSError as e:  # this would be "except OSError, e:" before Python 2.6
        if e.errno != errno.ENOENT:  # errno.ENOENT = no such file or directory
            raise  # re-raise exception if a different error occurred


def get_rbd_list():
    sp = subprocess.check_output('rbd list'.split())
    return sp.splitlines()


def get_random_password():
    return base64.b64encode(os.urandom(12)).decode()


def make_ext4_fs(path):
    subprocess.call(['mkfs.ext4', path])


def check_ext4_fs(path):
    subprocess.call(['e2fsck', '-y', path])


def create_rbd_image(image_name, size=13312, pool='rbd'):
    subprocess.call(['rbd', 'create', '-p', pool, '--size', str(size), image_name])


class VM(object):

    def __init__(self, vmid, basedir='/mnt/freeshell', lock_basedir='/dev/shm'):

        self.id = vmid
        self.basedir = basedir
        self.lock_basedir = lock_basedir
        self.rbd_name = 'shell-'+str(vmid)
        self.lock_path = lock_basedir + '/.shell-' + str(vmid) + '.lock'
        self.lock_path_s1 = self.lock_path + '.s1'
        self.lock_path_s2 = self.lock_path + '.s2'
        self.image_path = basedir + '/pool/' + str(vmid) + '/' + self.rbd_name
        self.rbd_mountpoint = basedir + '/pool/' + str(vmid)
        self.image_mountpoint = basedir + '/' + str(vmid)
        self.vm_private_path = self.image_mountpoint + '/' + str(vmid)
        self.vm_config_path = '/etc/vz/conf/' + str(vmid) + '.conf'
        self.vm_config_realpath = self.image_mountpoint + '/' + str(self.id) + '/ve.conf'

    def get_rbd_status(self):
        try:
            status = subprocess.check_output(['rbd', 'status', self.rbd_name], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            status = None
        return status

    def mount_rbd_image(self):
        """
        mount rbd image to mountpoint without check
        currently, use rbd-fuse
        """
        subprocess.call(['rbd-fuse', '-r', self.rbd_name, self.rbd_mountpoint])

    def mount_image(self):
        """
        mount VM image to VM's private path
        """
        subprocess.call(['mount', '-o', 'noatime', self.image_path, self.image_mountpoint])

    def umount_rbd_image(self):
        subprocess.call(['fusermount', '-u', self.rbd_mountpoint])

    def umount_image(self):
        subprocess.call(['umount', self.image_mountpoint])

    def mount(self):
        self.mount_stage_1()
        self.mount_stage_2()

    def mount_stage_1(self):
        logger.debug('mount_stage_1 %d' % self.id)
        if os.path.exists(self.lock_path_s1):
            logger.info('found stage_1 lock, do nothing')
            return
        status = self.get_rbd_status()
        if status is None:
            logger.critical('cannot find rbd image of %d' % self.id)
            raise RuntimeError()
        else:
            if b'none' in status:
                touch(self.lock_path_s1)
                os.makedirs(self.rbd_mountpoint, exist_ok=True)
                if os.path.ismount(self.rbd_mountpoint):
                    logger.info('%s is already a mountpoint' % self.rbd_mountpoint)
                else:
                    try:
                        self.mount_rbd_image()
                    except:
                        silentremove(self.lock_path_s1)
                        raise
            else:
                logger.critical('rbd image of %d is busy' % self.id)
                logger.critical(status)
                raise RuntimeError()

    def mount_stage_2(self):
        logger.debug('mount_stage_2 %d' % self.id)
        if os.path.exists(self.lock_path_s2):
            logger.info('found stage_2 lock, do nothing')
            return
        if os.path.exists(self.image_path):
            touch(self.lock_path_s2)
            try:
                check_ext4_fs(self.image_path)
                os.makedirs(self.image_mountpoint, exist_ok=True)
                if os.path.ismount(self.image_mountpoint):
                    logger.info('%s is already a mountpoint' % self.image_mountpoint)
                else:
                    self.mount_image()
                if not os.path.exists(self.vm_config_path):
                    if os.path.exists(self.vm_config_realpath):
                        os.symlink(self.vm_config_realpath, self.vm_config_path)
                    else:
                        logger.warning('cannot locate vm config of %d' % self.id)
            except:
                silentremove(self.lock_path_s2)
                raise
        else:
            logger.critical('rbd image of %d not found in mount_stage_2' % self.id)
            raise RuntimeError()

    def umount(self):
        self.umount_stage_2()
        self.umount_stage_1()

    def umount_stage_1(self):
        logger.debug('umount_stage_1 %d' % self.id)
        if os.path.exists(self.lock_path_s1):
            if os.path.exists(self.lock_path_s2):
                logger.critical('found stage_2 lock when umount_stage_1, abort')
                raise RuntimeError()
            else:
                if os.path.ismount(self.rbd_mountpoint):
                    self.umount_rbd_image()
                logger.info('status of rbd image %d: %s' % (self.id, self.get_rbd_status()))
                silentremove(self.lock_path_s1)
        else:
            logger.info('can\'t find stage_1 lock, do nothing')
            return

    def umount_stage_2(self):
        logger.debug('umount_stage_2 %d' % self.id)
        if os.path.exists(self.lock_path_s2):
            if os.path.ismount(self.image_mountpoint):
                self.umount_image()
            silentremove(self.lock_path_s2)
        else:
            logger.info('can\'t find stage_2 lock, do nothing')
            return

    def create_new_vm(self, template: str, config: str, attrs=None):
        logger.debug('creating new vm %d with template=%s, config=%s' % (self.id, template, config))
        status = self.get_rbd_status()
        if status is None:
            create_rbd_image(self.rbd_name)
            self.mount_stage_1()
            make_ext4_fs(self.image_path)
            self.mount_stage_2()
            try:
                subprocess.check_call(['vzctl', 'create', str(self.id),
                                 '--ostemplate', template,
                                 '--config', config,
                                 '--private', self.vm_private_path])
                if attrs is not None:
                    logger.debug('attrs is :')
                    self.vm_set_attrs(attrs)
            finally:
                self.umount_stage_2()
                self.umount_stage_1()
        else:
            logger.critical('rbd image %s has already existed' % self.rbd_name)
            raise NotImplementedError()

    def vm_set_attrs(self, attrs):
        for key, value in attrs.items():
            logger.debug('\t\t%s\t%s' % (key, value))
            subprocess.check_call(['vzctl', 'set', str(self.id), key, value, '--save'])

    def start_vm(self):
        logger.debug('starting vm %d' % self.id)
        if not os.path.exists(self.lock_path_s1):
            self.mount_stage_1()
        else:
            logger.debug('found stage_1 lock, skip mount_stage_1')
        if not os.path.exists(self.lock_path_s2):
            self.mount_stage_2()
        else:
            logger.debug('found stage_2 lock, skip mount_stage_2')
        if os.path.exists(self.vm_config_path):
            try:
                subprocess.check_call(['vzctl', 'start', str(self.id)])
            except:
                logger.critical('Error when starting vm %d, umount it' % self.id)
                self.umount_stage_2()
                self.umount_stage_1()
                raise
        else:
            logger.critical('can\'t start vm %d withoud a valid config' % self.id)

    def destroy(self):
        status = self.get_rbd_status()
        if status is None:
            logger.error('rbd image %s not exist' % self.rbd_name)
        else:
            self.umount()
            status = self.get_rbd_status()
            if b'none' in status:
                subprocess.check_call(['rbd', 'rm', self.rbd_name])
            else:
                logger.critical('rbd image %d is umounted but still busy while destroying' % self.id)
                logger.critical(status)
                raise RuntimeError()


def parse_arg():
    """
    list
    create id template
    mount id -ss
    umount id -ss
    destroy id
    nothing <-s-> mount rbd-fuse <-s-> mount fs
    :return:
    """
    parser = argparse.ArgumentParser(description='freeshell VM control')
    parser.add_argument('--version', action='version', version='%(prog)s {}'.format(VERSION))
    parser.add_argument('-v', '--verbose', action='count', default=0)
    parser.add_argument('-d', '--dir', metavar='basedir', type=str, default='/mnt/freeshell', help='work dir')
    subparsers = parser.add_subparsers(help='sub command', dest='cmd')

    # list
    parser_list = subparsers.add_parser('list')
    parser_list.add_argument('-a', '--all', action='store_true')

    # create
    parser_create = subparsers.add_parser('create')
    parser_create.add_argument('--config', type=str, default='freeshell')
    parser_create.add_argument('-H', '--hostname', type=str, help='vm hostname, default is vz-${CTID}')
    parser_create.add_argument('id', type=int, help='CTID')
    parser_create.add_argument('template', type=str)

    # mount
    parser_mount = subparsers.add_parser('mount')
    parser_mount.add_argument('id', type=int, help='CTID')
    parser_mount.add_argument('-s', dest='stage', type=int, choices=[1, 2], help='specify a mount stage')

    # umount
    parser_umount = subparsers.add_parser('umount')
    parser_umount.add_argument('id', type=int, help='CTID')
    parser_umount.add_argument('-s', dest='stage', type=int, choices=[1, 2], help='specify a umount stage')

    # start
    parser_start = subparsers.add_parser('start')
    parser_start.add_argument('id', type=int, help='CTID')

    # destroy
    parser_destroy = subparsers.add_parser('destroy')
    parser_destroy.add_argument('id', type=int, help='CTID')
    return parser.parse_args()


def setup_logger(args):
    global logger
    ch = logging.StreamHandler()
    fm = logging.Formatter('%(asctime)s\t%(levelname)s\t%(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    ch.setFormatter(fm)
    if args.verbose == 0:
        ch.setLevel(logging.ERROR)
    elif args.verbose == 1:
        ch.setLevel(logging.WARNING)
    elif args.verbose == 2:
        ch.setLevel(logging.INFO)
    else:
        ch.setLevel(logging.DEBUG)
    logger.addHandler(ch)


def main():
    args = parse_arg()
    setup_logger(args)
    if args.cmd == 'list':
        cmd = ['vzlist']
        if args.all:
            cmd += ['-a']
        subprocess.check_call(cmd)
    elif args.cmd == 'mount':
        vm = VM(args.id)
        if args.stage is None:
            vm.mount()
        elif args.stage == 1:
            vm.mount_stage_1()
        elif args.stage == 2:
            vm.mount_stage_2()
    elif args.cmd == 'umount':
        vm = VM(args.id)
        if args.stage is None:
            vm.umount()
        elif args.stage == 1:
            vm.umount_stage_1()
        elif args.stage == 2:
            vm.umount_stage_2()
    elif args.cmd == 'create':
        vm = VM(args.id)
        if args.hostname is None:
            args.hostname = 'vz-' + str(args.id)
        root_password = get_random_password()
        attrs = {
            '--ipadd': '10.70.%d.%d' % (args.id // 256, args.id % 256),
            '--nameserver': '202.38.64.17',
            '--hostname': args.hostname,
            '--userpasswd': 'root:' + root_password
        }
        print('#####################################')
        print('## root password: %s ##' % root_password)
        print('#####################################')
        vm.create_new_vm(args.template, args.config, attrs)
    elif args.cmd == 'start':
        vm = VM(args.id)
        vm.start_vm()
    elif args.cmd == 'destroy':
        vm = VM(args.id)
        vm.destroy()
    else:
        logger.critical('unknown command %s' % args.cmd)
        raise NotImplementedError()

if __name__ == '__main__':
    main()
