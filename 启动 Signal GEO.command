#!/bin/zsh
cd -- "${0:A:h}"
print 'Signal GEO 本地开发服务：http://127.0.0.1:8765'
print '保持此窗口打开，按 Ctrl+C 停止服务。'
/usr/bin/open 'http://127.0.0.1:8765'
python3 server.py
