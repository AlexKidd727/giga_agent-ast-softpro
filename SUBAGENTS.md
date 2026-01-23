# Подагенты
## [Агент презентаций](backend/graph/giga_agent/agents/presentation_agent)
Создает презентации с помощью [Reveal.js](https://revealjs.com/). Генерирует слайды / изображения к ним.

Так же, имеет возможность подгружать в презентации изображения/графики из основного агента GigaAgent.

Пример работы: [переписка](/docs/examples/mortgage/landing_presentation_chat.pdf), [презентация](/docs/examples/mortgage/presentation.pdf)
## [Агент генерации подкастов](backend/graph/giga_agent/agents/podcast)
Создает подкаст на основе переписки / контента по ссылке. Использует синтез [SaluteSpeech](https://developers.sber.ru/portal/products/smartspeech).

Пример работы: [переписка](/docs/examples/mortgage_podcast/podcast_chat.pdf), [подкаст](/docs/examples/mortgage_podcast/podcast.mp3)
## [Агент Мемов](backend/graph/giga_agent/agents/meme_agent)
Создает мемы. Достаточно простой агент, можно использовать в качестве примера для создания своего.

Мемы со сберкотом, может генерить только на GigaChat API Kandinsky

Пример работы: [чат](/docs/examples/memes/chat.pdf)

![мем_1](/docs/examples/memes/meme1.jpeg), ![мем_2](/docs/examples/memes/meme2.jpg)
## [Агент по созданию Lean Canvas](backend/graph/giga_agent/agents/lean_canvas)
Создает LeanCanvas — популярный инструмента для описания бизнес-модели стартапов.

Пример работы: [переписка](docs/examples/lean_canvas/lean_canvas.pdf)
## [Агент по созданию лендингов](backend/graph/giga_agent/agents/landing_agent)
Создает лендинг

Пример работы: [переписка](/docs/examples/mortgage/landing_presentation_chat.pdf)
## [Агент исследователь города](backend/graph/giga_agent/agents/gis_agent)
Интересные места + карта с помощью 2GIS

Пример работы: [переписка](/docs/examples/city_explorer/city_explorer.pdf)

## Как создать своего под-агента в GigaAgent
Желательно сделать его в виде графа на LangGraph. 
Пример, реализации простых агентов можете посмотреть в [Агенте Мемов](meme_agent) или [Lean Canvas](lean_canvas). Прочитать подробнее про создание агента Lean Canvas можно [здесь](https://github.com/ai-forever/gigachain/blob/master/cookbook/lean_canvas/lean_canvas_agent.ipynb).

После того как вы создадите граф, путь до него нужно положить в файл [langgraph.json](/backend/graph/langgraph.json) в ключ `"graph"`.
Это позволить вызывать агента с помощью LangGraph API

Вызов агента происходит с помощью tool-calling.

Также настроить названия агента + названия узлов которые выполняются (на фронтенде) можно [здесь](/front/src/config.ts). В переменных `TOOL_MAP` и `PROGRESS_AGENTS`. **Важно**: Такой вариант отображения пока временный. Скорее всего названия агентов и тулов я буду выносить на бэкенд.

## Как в результате работы прикладывать вложения
В результате работы тулов / агентов можно возвращать вложения (картинки / аудио / html-страницы), который GigaAgent сможет потом отобразить в переписке с пользователем.

Для этого в результате работы вам нужно вернуть ключ `giga_attachments` со следующей схемой отображения:
```json
{
  "giga_attachments": [
    {
      "type": "image/png",
      "file_id": "uuid",
      "data": "base64-string"
    }
  ]
}
```

Пример html:
```json
{
  "giga_attachments": [
    {
      "type": "text/html",
      "file_id": "uuid",
      "data": "html страница"
    }
  ]
}
```

Пример аудио:
```json
{
  "giga_attachments": [
    {
      "type": "audio/mp3",
      "file_id": "uuid",
      "data": "base64 аудио"
    }
  ]
}
```
