/etc/modprobe.d/loop.conf:
  file.managed:
    - source: salt://alkaid/freeshellv2/loop.conf
    - user: root
    - group: root
    - mode: 644 
    - replace: True
    - create: True
/etc/sysctl.d/99-freeshell.conf:
  file.managed:
    - source: salt://alkaid/freeshellv2/99-freeshell.conf
    - user: root
    - group: root
    - mode: 644 
    - replace: True
    - create: True
/etc/iproute2/rt_tables:
  file.managed:
    - source: salt://alkaid/freeshellv2/rt_tables
    - user: root
    - group: root
    - mode: 644 
    - replace: True
    - create: True
/etc/sysconfig/iptables:
  file.managed:
    - source: salt://alkaid/freeshellv2/iptables
    - user: root
    - group: root
    - mode: 600
    - replace: True
    - create: True
