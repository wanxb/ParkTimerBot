import logging
from datetime import datetime, timedelta
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import configparser

# 默认配置（分钟为单位），可在 config.ini 中覆盖
CONFIG = {
    'FREE_MINUTES': 30,
    'PRE_ALERT_MINUTES': 5,
    'REMIND_INTERVAL_MINUTES': 60,
    'REMIND_HOURS': 168,
    'EXIT_GRACE_MINUTES': 30,
}

# 设置日志
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# 存储用户数据
user_sessions = {}

# --- 辅助函数：格式化时间 ---
def format_duration(seconds):
    abs_sec = abs(int(seconds))
    hh = abs_sec // 3600
    mm = (abs_sec % 3600) // 60
    ss = abs_sec % 60
    if hh > 0:
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    return f"{mm:02d}:{ss:02d}"

# --- 1. 生成输入框常驻按钮 ---
def get_reply_keyboard(mode):
    if mode == 'PARKING':
        keyboard = [
            ["🔄 刷新/查看时间"],
            ["➕ 1m", "➖ 1m"],
            ["✅ 已缴费，开始离场"]
        ]
    elif mode == 'EXIT':
        keyboard = [["🔄 刷新时间"], ["⏹ 结束并重置"]]
    else:
        keyboard = [["🅿️ 开始停车计时"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- 2. 核心：获取显示内容 ---
def get_display_content(session):
    now = datetime.now()
    if session['mode'] == 'PARKING':
        total_sec = int((now - session['start_time']).total_seconds()) + (session['offset_min'] * 60)
        status = "🟢 【正在计费】"
        adj_str = f"\n_(手动调校: {session['offset_min']}m)_" if session['offset_min'] != 0 else ""
    else:
        passed_sec = int((now - session['start_time']).total_seconds())
        total_sec = (CONFIG['EXIT_GRACE_MINUTES'] * 60) - passed_sec
        status = "🔵 【离场倒计时】"
        adj_str = ""
    
    display_sec = max(0, total_sec)
    time_str = format_duration(display_sec)
    text = f"{status}\n\n      ⏱ **{time_str}**\n{adj_str}"
    return text, total_sec

# --- 3. 自动刷新与自动重置任务 ---
async def auto_refresh_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    session = user_sessions.get(chat_id)

    if not session or session['mode'] == 'IDLE':
        job.schedule_removal()
        return

    text, total_sec = get_display_content(session)
    
    if session['mode'] == 'EXIT' and total_sec <= 0:
        session['mode'] = 'IDLE'
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"🏁 {CONFIG['EXIT_GRACE_MINUTES']}分钟离场宽限期已过，计时已自动重置。", 
            reply_markup=get_reply_keyboard('IDLE')
        )
        job.schedule_removal()
        return

    try:
        if 'last_msg_id' in session:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=session['last_msg_id'],
                text=text,
                parse_mode='Markdown'
            )
    except Exception:
        pass

# --- 4. 核心修改：一周提醒逻辑 ---
def schedule_reminders(context, chat_id, start_time, offset):
    # 清除旧提醒
    jobs = context.job_queue.get_jobs_by_name(f"remind_{chat_id}")
    for job in jobs: job.schedule_removal()
    
    now = datetime.now()
    # 当前已停分钟数（含调校）
    current_min = int((now - start_time).total_seconds() / 60) + offset

    remind_points = []
    # 1. 初始免费期的跳档预警 (free_minutes - pre_alert)
    first_point = max(0, CONFIG['FREE_MINUTES'] - CONFIG['PRE_ALERT_MINUTES'])
    if current_min < first_point:
        remind_points.append(first_point)

    # 2. 循环生成未来 N 小时 的提醒点
    for n in range(1, int(CONFIG['REMIND_HOURS']) + 1):
        point = n * int(CONFIG['REMIND_INTERVAL_MINUTES']) - int(CONFIG['PRE_ALERT_MINUTES'])
        if point > current_min:
            remind_points.append(point)

    # 3. 注册任务
    for m in remind_points:
        delay = (m * 60) - (int((now - start_time).total_seconds()) + offset * 60)
        if delay > 0:
            context.job_queue.run_once(
                send_alarm, delay, chat_id=chat_id, name=f"remind_{chat_id}", data=m
            )

async def send_alarm(context: ContextTypes.DEFAULT_TYPE):
    # 如果是数值则显示分钟，如果是文字则显示文字
    msg_data = context.job.data
    content = f"{msg_data} 分钟" if isinstance(msg_data, int) else msg_data
    await context.bot.send_message(context.job.chat_id, text=f"⚠️ 【跳档预警】\n当前已接近计费节点：{content}！")

# --- 5. 消息处理逻辑 ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id
    session = user_sessions.setdefault(chat_id, {'mode': 'IDLE', 'offset_min': 0})

    if text == "🅿️ 开始停车计时":
        session.update({'mode': 'PARKING', 'start_time': datetime.now(), 'offset_min': 0})
        msg = await update.message.reply_text("🚀 计时启动。提醒已覆盖未来一周。", reply_markup=get_reply_keyboard('PARKING'))
        session['last_msg_id'] = msg.message_id
        schedule_reminders(context, chat_id, session['start_time'], 0)
        context.job_queue.run_repeating(auto_refresh_job, interval=60, first=60, chat_id=chat_id)

    elif text == "✅ 已缴费，开始离场":
        session.update({'mode': 'EXIT', 'start_time': datetime.now(), 'offset_min': 0})
        msg = await update.message.reply_text(f"🔵 已进入离场模式，开始{CONFIG['EXIT_GRACE_MINUTES']}分钟倒计时。", reply_markup=get_reply_keyboard('EXIT'))
        session['last_msg_id'] = msg.message_id
        # 在离场宽限期前提前提醒（exit_grace - pre_alert）
        warn_delay = max(0, (int(CONFIG['EXIT_GRACE_MINUTES']) - int(CONFIG['PRE_ALERT_MINUTES'])) * 60)
        if warn_delay > 0:
            context.job_queue.run_once(send_alarm, warn_delay, chat_id=chat_id, data="离场宽限期即将结束")

    elif "刷新" in text:
        if session['mode'] == 'IDLE':
            await update.message.reply_text("未在计时。", reply_markup=get_reply_keyboard('IDLE'))
        else:
            content, _ = get_display_content(session)
            msg = await update.message.reply_text(content, parse_mode='Markdown')
            session['last_msg_id'] = msg.message_id

    elif text in ["➕ 1m", "➖ 1m"] and session['mode'] == 'PARKING':
        adj = 1 if "➕" in text else -1
        session['offset_min'] = max(-60, min(60, session['offset_min'] + adj))
        schedule_reminders(context, chat_id, session['start_time'], session['offset_min'])
        content, _ = get_display_content(session)
        msg = await update.message.reply_text(f"校准成功：\n{content}", parse_mode='Markdown')
        session['last_msg_id'] = msg.message_id

    elif text == "⏹ 结束并重置":
        session['mode'] = 'IDLE'
        for j_name in [f"remind_{chat_id}", f"refresh_{chat_id}"]:
            for j in context.job_queue.get_jobs_by_name(j_name): j.schedule_removal()
        await update.message.reply_text("🏁 计时已结束。", reply_markup=get_reply_keyboard('IDLE'))



def main(config_path: str = 'config.ini'):
    import traceback
    import os
    import configparser

    # 1. 尝试从环境变量读取
    token = os.environ.get('TOKEN')

    # 2. 如果环境变量没有，再尝试读取本地 config.ini（兼容本地开发）
    if not token:
        config = configparser.ConfigParser()
        # 检查文件是否存在，避免报错
        if os.path.exists('config.ini'):
            config.read('config.ini')
            token = config.get('DEFAULT', 'TOKEN', fallback=None)
        elif os.path.exists('config.example.ini'):
            # 也可以 fallback 到 example，但通常 example 里没有真 Token
            config.read('config.example.ini')
            token = config.get('DEFAULT', 'TOKEN', fallback=None)

    # 3. 检查最终是否拿到了 Token
    if not token or "your-telegram-bot-token" in token:
        print("错误：未找到有效的 BOT TOKEN")
        exit(1)

    # override CONFIG from config file when present
    for key in ('FREE_MINUTES', 'PRE_ALERT_MINUTES', 'REMIND_INTERVAL_MINUTES', 'REMIND_HOURS', 'EXIT_GRACE_MINUTES'):
        if key in config['DEFAULT']:
            try:
                CONFIG[key] = int(config['DEFAULT'][key])
            except Exception:
                pass

    print(f"Starting ParkTimerBot with FREE_MINUTES={CONFIG['FREE_MINUTES']}, PRE_ALERT_MINUTES={CONFIG['PRE_ALERT_MINUTES']}, REMIND_INTERVAL_MINUTES={CONFIG['REMIND_INTERVAL_MINUTES']}, REMIND_HOURS={CONFIG['REMIND_HOURS']}, EXIT_GRACE_MINUTES={CONFIG['EXIT_GRACE_MINUTES']}")
    print(f"Using token prefix: {TOKEN[:6]}... (hidden)")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("停车助手已就绪", reply_markup=get_reply_keyboard('IDLE'))))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    try:
        print("Bot is running...")
        app.run_polling()
    except Exception as e:
        print('Unhandled exception in run_polling:')
        traceback.print_exc()
