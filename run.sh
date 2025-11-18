##!/bin/bash
#
#cd ~/chat_summarizator
#
## Останавливаем если запущено
#pkill -f "python src/main_with_proxy.py"
#
## Ждем завершения
#sleep 2
#
## Запускаем заново
#nohup python src/main_with_proxy.py > output.log 2>&1 &
#
#echo "✅ Приложение перезапущено (PID: $!)"
#echo "📊 Логи: tail -f output.log"

# одной командой
pkill -f "python src/main_with_proxy.py" && sleep 2 && nohup python src/main_with_proxy.py > output.log 2>&1 &