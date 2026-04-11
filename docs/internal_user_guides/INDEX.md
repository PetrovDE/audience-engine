# Внутренние User Guides (Stage 11)

Короткие практические инструкции для внутренних ролей AudienceEngine.

## Что входит
- [FIRST_15_MINUTES.md](FIRST_15_MINUTES.md) - общий старт для любого пользователя
- [ADMIN_OPERATOR.md](ADMIN_OPERATOR.md) - гайд для Админа/Оператора
- [DATA_ENGINEER.md](DATA_ENGINEER.md) - гайд для Инженера данных
- [ML_ANALYST.md](ML_ANALYST.md) - гайд для ML-аналитика
- [CAMPAIGN_USER.md](CAMPAIGN_USER.md) - гайд для Пользователя кампании

## Важные ограничения этого пакета
- Гайды описывают только реализованные сейчас маршруты `/operator/*`.
- Изображения лежат в `docs/internal_user_guides/images/` и встроены в ролевые документы.
- Если конкретный слот не покрыт живым кадром, он отмечается как `Placeholder`.

## База для проверки
- Runtime-проверка маршрутов и RU-навигации выполнена 2026-04-11 через FastAPI `TestClient`.
- Ролевая матрица сверена с `services/retrieval_api/operator_access.py`.
- UAT-контекст и ожидания сверены с `docs/UAT_ROLE_FLOWS.md` и `docs/UAT_SCENARIOS.md`.
- Live-capture скриншотов для Stage 11B выполнен 2026-04-11 через Playwright (локальный `uvicorn`, role-specific логины).
