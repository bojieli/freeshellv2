#!/bin/sh
ORIG_PATH=../systemd/freeshell_bridge.service
INSTALL_PATH=/etc/systemd/system/freeshell_bridge.service
HOSTID=${HOSTNAME#*-}
cp ${ORIG_PATH} ${INSTALL_PATH}
sed -i -e "s/\${HOSTID}/${HOSTID}/g" ${INSTALL_PATH}
systemctl daemon-reload
