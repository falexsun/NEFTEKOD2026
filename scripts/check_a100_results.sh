#!/bin/bash
# Проверка результатов обучения на A100

SERVER="${A100_SERVER:-a100-server}"
REMOTE_DIR="/workspace/neftekod"

echo "================================================"
echo "ПРОВЕРКА РЕЗУЛЬТАТОВ НА A100"
echo "================================================"
echo ""

# Проверка логов
echo "📋 Последние 50 строк лога:"
echo "------------------------------------------------"
ssh $SERVER "tail -50 $REMOTE_DIR/scripts/advanced_training.log"
echo ""

# Проверка наличия результатов
echo "================================================"
echo "📁 Файлы результатов:"
echo "------------------------------------------------"
ssh $SERVER "ls -lh $REMOTE_DIR/scripts/*.json 2>/dev/null && ls -lh $REMOTE_DIR/models/*.pkl 2>/dev/null" || echo "Результаты еще не готовы"
echo ""

# Если есть результаты - показать метрики
if ssh $SERVER "[ -f $REMOTE_DIR/scripts/advanced_training_results.json ]"; then
    echo "================================================"
    echo "📊 РЕЗУЛЬТАТЫ ОБУЧЕНИЯ:"
    echo "------------------------------------------------"
    ssh $SERVER "python3 << 'EOF'
import json
with open('$REMOTE_DIR/scripts/advanced_training_results.json') as f:
    data = json.load(f)

print('⏱️  Общее время:', data.get('total_time', 'N/A'), 'сек')
print('🏆 Моделей обучено:', data.get('total_models_trained', 'N/A'))
print()
print('ТОП-3 МОДЕЛИ:')
print('-' * 70)
for model in data.get('top_10_models', [])[:3]:
    print(f"  #{model['rank']} {model['model_type']}")
    print(f"     MAE: {model['mae']:.2f}")
    print(f"     R²: {model['r2']:.4f}")
    print(f"     Время: {model['time']:.2f}s")
    print()

print('АНСАМБЛИ:')
print('-' * 70)
ens = data.get('ensemble', {})
if 'simple_voting' in ens:
    print(f"  Simple Voting: MAE={ens['simple_voting']['mae']:.2f}")
if 'weighted_voting' in ens:
    print(f"  Weighted Voting: MAE={ens['weighted_voting']['mae']:.2f}")
print()

baseline = data.get('baseline_comparison', {})
print('СРАВНЕНИЕ С BASELINE:')
print('-' * 70)
print(f"  Baseline MAE: {baseline.get('baseline_mae', 'N/A'):.2f}")
print(f"  Новая лучшая MAE: {baseline.get('new_best_mae', 'N/A'):.2f}")
print(f"  Улучшение: {baseline.get('improvement_pct', 'N/A'):+.2f}%")
EOF
" || echo "Не удалось прочитать результаты"
else
    echo "❌ Результаты еще не готовы"
    echo ""
    echo "Проверьте через несколько минут или смотрите лог:"
    echo "  ssh $SERVER 'tail -f $REMOTE_DIR/scripts/advanced_training.log'"
fi

echo ""
echo "================================================"
