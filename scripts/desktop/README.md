# 云桌面自动显示监控页面

## 工作原理

- supervisor 管理一组桌面服务 (cua-vnc)
- 新增 `monitor-browser` program: 自动启动 Chrome 到 http://localhost:8000/monitor
- Chrome 用 `--app` 模式: 纯页面无地址栏,沉浸式监控
- 持久化 profile (`/home/browser/.config/stockagent-monitor`): 记住 cookies/localStorage
- 崩了 supervisor 自动重启

## 安装

```bash
sudo cp start-monitor-browser.sh /opt/browser-vnc/
sudo chmod +x /opt/browser-vnc/start-monitor-browser.sh
sudo cp browser-vnc.conf /etc/supervisor/conf.d/
sudo supervisorctl reread && sudo supervisorctl update
```

## 验证

```bash
sudo supervisorctl status cua-vnc:monitor-browser
# 应显示 RUNNING

# 截图验证
DISPLAY=:99 import -window root /tmp/check.png
```

## 与扫描器自愈联动

`scanner_autoheal.sh` (盘前 9:25 cron) 会:
1. 启动扫描器
2. 同步前端 build
3. 检查浏览器,崩了重启,在跑则刷新页面拿最新代码

这样**云电脑打开 = VNC 连接 = 直接看到最新数据的监控页面**
