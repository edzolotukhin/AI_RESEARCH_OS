# AI Research OS Development Rules

## Общие правила

- Всегда изменяем полный файл, а не отдельные строки.
- После каждого изменения запускаем проект.
- Не добавляем новую архитектуру без необходимости.
- Один спринт = одна законченная задача.

## Prompts

- Все prompts находятся в папке prompts/
- Формат файлов: .md
- В constants/prompts.py хранится имя без расширения

## Domain

- Все сущности находятся в domain/
- Value Objects — в domain/value_objects/

## Services

Service отвечает за бизнес-логику.

## Roles

Role работает с LLM и ничего не знает о Workflow.