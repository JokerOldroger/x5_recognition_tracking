# 叮咚 X5 上位机完整代码

整合日期为 2026 年 10 月 25 日，版本为 x5-20261025-final。

适用环境为 RDK X5、官方 Ubuntu 22.04、TROS Humble、USB 摄像头，以及通过 USB 通信口连接的 H60 控制板。默认串口 /dev/ttyACM0，115200 波特率。板子已有 pyserial 时不必重新安装。

## 已整合功能

- 接收官方 hand_gesture_detection 的识别结果，默认话题 /hobot_hand_gesture_detection。
- 比耶时转圈再点头，张开手掌时摇头再后退。
- 拇指向左或向右时，先转向、短暂停顿，再向前走一小段。转向按时间控制，需要按实车调整，不保证固定角度。
- 上电遥控。识别程序启动后单按 START 申请，确认后进入手势模式。再次按 START 退出。其他手柄操作仍可接管。
- 输出 H60 保存的退出原因和手柄数据，便于排查无人操作时退出的问题。
- 摄像头启动前等待系统时间有效并稳定五秒。等待不会在三分钟后退出，时间满足条件后自动继续。此脚本只检查时间，不负责校时。
- 保留过期视觉消息过滤、手势稳定确认、重复触发限制和视觉中断停车。

蜂鸣器和 START 事件由 H60 固件实现。本包与当前使用的 dingdong_exit_diagnostics.hex 配套。开机短音只表示 H60 已启动，不能表示 X5 已就绪。进入手势模式两声短音，退出一声长音，申请过期或控制通信超时三声短音。刚开机应等 X5 摄像头和识别启动后再按 START。

## 更新现有 X5

完整包内不包含 config.json，只提供 config.example.json，避免解压时覆盖板子上已经调好的参数。prepare_config.py 会备份原配置，补齐缺少的字段，保留串口和动作参数，并设置上电遥控及启用 START 申请。

将 dingdong_x5_latest_20261025.zip 上传到 /home/sunrise。先架空轮子，再执行。

```bash
sudo systemctl stop dingdong
python3 -m zipfile -e /home/sunrise/dingdong_x5_latest_20261025.zip /home/sunrise/dingdong_x5
cd /home/sunrise/dingdong_x5
python3 prepare_config.py
sudo bash install_service.sh
sudo systemctl start dingdong
sudo journalctl -b -u dingdong -n 30 -f -o cat
```

prepare_config.py 如果提示配置校验失败，先修正所报告的参数，不要继续启动运动。

新板首次安装也可以使用上述步骤。原配置不存在时，prepare_config.py 使用代码内默认值创建 config.json。示例配置供查看，不必手动复制。

看到 Fresh gesture messages received 表示上位机收到了有效视觉消息。此时单按 START，两声短音后可以测试手势。MCU granted host control 表示 H60 已确认控制权。Victory: turn then nod 表示动作已触发；末尾附带 recognition only, no motion 时表示只识别、不执行动作。

日志窗口按 Ctrl+C 只退出日志查看。若误按 Ctrl+S 导致终端暂停，可以用 Ctrl+Q 恢复显示。

## 动作参数

默认轮速为 120 mm/s。比耶转圈三秒，再点头。张开手掌先摇头，再后退 0.6 秒。左右指默认转向 0.6 秒，停顿 0.2 秒，再以 120 mm/s 前进 0.8 秒。旧配置中的已有校准值会保留，实际数值以板子的 config.json 为准。

手势需稳定保持，建议保持一秒。相同手势持续不放只触发一次，收回手约一秒后再做。完整手部要出现在摄像头画面内。

## 文件说明

| 文件 | 用途 |
|---|---|
| run.sh | 启动时间检查、官方识别程序和上位机 |
| wait_clock.py | 等待有效且稳定的系统时间 |
| install_service.sh | 安装和启用开机服务 |
| prepare_config.py | 初始化或合并当前配置 |
| config.example.json | 默认配置示例 |
| dingdong/bridge.py | 识别订阅、动作调度、控制申请和诊断日志 |
| dingdong/core.py | 通信帧、手势确认和动作阶段 |
| dingdong/transport.py | 串口请求、回复和退出原因查询 |
| dingdong/cli.py | 单独调试串口和动作 |
| apply_*_update.py | 旧版配置迁移工具，新整合包使用 prepare_config.py 即可 |
| tests/ | 无需 ROS 和实机的自动测试 |
| RELEASE.json | 版本、兼容固件和验证信息 |

## 测试与已知情况

在项目目录运行 python3 -m unittest discover -s tests。测试不需要连接机器人，也不替代实机测试。

实机已观察到成功申请控制、有效视觉消息和比耶动作触发。此前摄像头曾出现 Invalid v4l2 format 并退出，后续独立摄像头测试及整套程序测试没有复现。该间歇性问题尚未确认根治，本包未修改官方摄像头驱动。日志中的退出原因应结合当时的实际操作判断。

若摄像头停止供图，上位机会取消动作并发送零速。识别进程存在但摄像头子进程退出时，服务可能仍显示运行，须结合 No fresh vision 和相机错误判断。服务不会自动重启整个识别程序，避免意外重新申请控制。无网络且系统时间始终不正确时，会持续等待，需要先解决系统时间。

本包仅包含 X5 上位机代码、配置示例、说明和测试，不包含 STM32 源码、烧录固件或 /opt/tros 中的模型和算法安装包。当前配套 H60 固件已烧录时无需再次烧录。
