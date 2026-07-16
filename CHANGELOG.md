# CHANGELOG

## Sprint 6

### Added
- ProjectBrief domain model
- ProjectBriefBuilder service
- Stable demonstration in main.py
- sandbox.py for development and testing

### Architecture
- main.py is used only for product demonstration.
- sandbox.py is used only for experiments.
- Files are changed only by replacing the entire file.
- One sprint = one completed result.

---

## Sprint 7

### Added
- ReadinessRules works with ProjectBrief.
- Validation of required business fields.
- ReadinessRules successfully tested through sandbox.py.

### Business Rules
Required fields:
- client
- research_goal
- research_objectives
- target_audience
- geography

### Architecture
- After ProjectBriefBuilder the system works only with domain objects.
- Dictionaries are used only as input for creating ProjectBrief.
# CHANGELOG

## Sprint 9

### Added

- Создан PromptRepository.
- Создан PromptBuilder.
- Создан OpenAIService.
- Создан JsonParser.
- Создан ResearchDesignFactory.
- Добавлены константы Prompt и ResearchDesignFields.

### Changed

- ResearchDesigner переведен на работу через GPT.
- Промпт Research Designer вынесен в отдельный файл.
- Создание ResearchDesign вынесено в Factory.

### Fixed

- Исправлена работа с OpenAI API.
- Добавлена загрузка API-ключа через .env.
- Исправлен разбор JSON-ответа от LLM.

### Architecture

ResearchDesigner теперь работает по цепочке:

ProjectBrief
→ PromptBuilder
→ PromptRepository
→ OpenAIService
→ JsonParser
→ ResearchDesignFactory
→ ResearchDesign