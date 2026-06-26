#!/bin/bash
# Retail Location Analyzer — запуск в один клик
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Попробовать виртуальное окружение, если есть
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "🏪 Запуск Retail Location Analyzer..."
echo "   Папка: $DIR"
echo ""

# Установка зависимостей при первом запуске
if [ ! -f ".deps_installed" ]; then
    echo "📦 Устанавливаю зависимости..."
    pip install -q -r requirements.txt
    touch .deps_installed
    echo "✅ Готово"
    echo ""
fi

# Запуск
streamlit run app.py --server.headless true

echo ""
echo "Нажмите Enter для выхода..."
read
