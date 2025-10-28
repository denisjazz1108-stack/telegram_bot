#!/bin/bash
# Скрипт для деплоя Telegram-бота на Render через GitHub

# Добавляем все изменения
git add .

# Создаём коммит с текущей датой и временем
git commit -m "Обновление бота $(date +'%Y-%m-%d %H:%M:%S')"

# Отправляем на GitHub
git push origin main

echo "✅ Изменения отправлены на GitHub. Render автоматически деплоит проект."
