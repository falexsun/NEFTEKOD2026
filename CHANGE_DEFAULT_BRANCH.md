# Как сделать main ветку дефолтной на GitHub

К сожалению, я не могу изменить настройки GitHub через API напрямую, но могу показать вам как это сделать:

## Способ 1: Через веб-интерфейс GitHub (2 минуты)

1. Откройте: https://github.com/falexsun/NEFTEKOD2026

2. Перейдите в **Settings** (вкладка вверху)

3. В левом меню найдите **Branches**

4. В разделе **Default branch** увидите текущую ветку (сейчас `dev`)

5. Нажмите кнопку со стрелками (⇄) или "Switch default branch"

6. Выберите **main** из списка

7. Нажмите **Update**

8. Подтвердите изменение

**Готово!** Теперь main - дефолтная ветка.

---

## Способ 2: Через GitHub CLI (если установлен)

```bash
# Если у вас установлен gh CLI:
gh repo edit falexsun/NEFTEKOD2026 --default-branch main
```

---

## Что изменится:

После смены дефолтной ветки на `main`:
- При открытии https://github.com/falexsun/NEFTEKOD2026 будет показываться main
- При клонировании `git clone` будет checkout на main
- Pull requests по умолчанию будут в main
- README из main будет на главной странице

---

## Проверка:

После изменения откройте:
https://github.com/falexsun/NEFTEKOD2026

Должны увидеть:
- Вкладка `main` активна
- README с новым дизайном (без эмодзи, с MAE badges)
- Mermaid диаграмма

---

**Вам нужно сделать это вручную через Settings → Branches на GitHub!**
