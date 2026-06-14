# Chat Session Model Selector

## Goal

Add a GPT-style model selector to the chat conversation header. Each conversation independently uses either automatic task-based routing or one explicitly selected supported model.

## Behavior

- New conversations default to `auto`; existing conversations without model settings also resolve to `auto`.
- A manual selection affects only the current conversation. Switching conversations restores that conversation's saved selection, including after page refresh or backend restart.
- Automatic mode keeps the existing text/vision routing logic. Manual mode fixes the current conversation to the selected supported model.
- Changing the selection does not append a system message or otherwise modify chat history. The UI shows a short success state near the selector; errors remain local to the selector.
- Unsupported or removed models are rejected by the backend. If a previously saved model is no longer supported, the conversation falls back to automatic mode and returns the normalized state.

## Backend And Persistence

- Store model routing fields in the existing `conversation_state.state_json`, using `model_route_mode` (`auto` or `manual`) and `selected_chat_model` (empty in auto mode).
- Refactor model routing so selection is loaded from the current conversation before each model-routed request. Do not mutate the global `Settings.model` when a conversation selects a model.
- New and switched sessions load their own routing state; deletion naturally removes the associated conversation state through the existing session lifecycle.
- Add authenticated chat model endpoints:
  - `GET /api/chat/models?user_id=...&session_id=...` returns available models, automatic option metadata, current selection, normalized route mode, and the most recently active model for that conversation when known.
  - `POST /api/chat/models/select` accepts `user_id`, `session_id`, and `model` where `model="auto"` enables automatic routing; it validates ownership/session existence and returns the normalized selector state.
- Model items expose a stable model id plus a backend-derived capability label (`text` or `vision`). No provider secrets or credentials are returned.

## Frontend

- Add a compact selector in the conversation header before the upload action. The trigger reads `自动选择` in auto mode and the model id in manual mode.
- The menu places `自动选择` first with a short task-routing description, followed by supported models with text/vision labels and a checkmark on the current selection.
- Load selector state whenever login identity or current session changes. Disable it while loading, switching sessions, changing the model, or sending a request.
- On selection, update the selector from the API response without adding a chat message. Show a brief inline `已切换` status; keep failures beside the selector and retain the previous confirmed value.
- On narrow layouts, keep the selector available in the conversation header with truncated model text and an accessible title.

## Compatibility And Testing

- Preserve current chat request/response shapes and automatic routing behavior. Direct deterministic routes remain direct and do not pretend to use the manually selected LLM.
- Unit-test state defaults, per-session isolation, persistence, unsupported-model fallback, and absence of model-switch system messages.
- API-test model listing and selection, authentication/ownership checks, invalid model rejection, and session switching.
- Frontend tests assert selector presence, loading on session changes, local success/error handling, no injected chat message, and responsive availability.
- Run backend tests, the complete frontend suite, production build, and browser checks for auto/manual selection across two conversations and page refresh.

## Assumptions

- Supported models continue to come from `Settings.supported_models` / `ZAI_SUPPORTED_MODELS`.
- `自动选择` is a UI label; the API uses the stable value `auto`.
- The selector controls conversational LLM routing, not GIS analysis algorithms such as RF, XGBoost, or LSTM.
