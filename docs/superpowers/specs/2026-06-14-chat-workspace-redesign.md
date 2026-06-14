# Chat Workspace Redesign

## Goal

Redesign the chat page around the approved minimal session-sidebar layout. Remove information already owned by the global application shell, improve message focus, and establish a clearer button hierarchy without changing chat behavior or backend contracts.

## Information Architecture

- Remove the in-chat account card, assistant identity header, GIS Agent badge, capability subtitle, and persistent workspace statistics card from page mode.
- Keep the global top-right account area as the only account identity and logout surface.
- Use a compact left rail for conversation management only: primary new-chat button, recent session list, selected state, timestamps or message metadata when available, and session deletion through a contextual action.
- Use a compact conversation header in the main pane with the current session title, message count, upload action, and overflow actions. Keep file upload behavior and accepted file types unchanged.
- Keep floating chat mode functional. Apply the simplified identity treatment there while preserving its close and resize controls.

## Conversation Experience

- Replace the empty-state prompt stack with a centered welcome block and four concise task cards: workspace inspection, fusion modeling, map creation, and data download preparation.
- Keep existing prompt text as the submitted payload, while using shorter labels and descriptions in the visible cards.
- Preserve message rendering, optimistic message IDs, edit-and-regenerate, retry, voice input, session switching, upload, and thesis workflow behavior.
- Keep the composer anchored to the bottom with a neutral container, clear focus state, secondary voice button, and blue primary send button.

## Visual System

- Use the existing blue brand palette with restrained gradients limited to primary actions and selected accents.
- Reduce glass blur, oversized shadows, pills, and decorative assistant branding in the page workspace.
- Standardize chat controls around 10-12 px radii, subtle slate borders, white surfaces, and compact 36-42 px control heights.
- Define chat-specific primary, secondary, icon, danger, session-row, prompt-card, and composer styles. Hover states change color, border, or shadow without layout movement.
- Preserve dark-mode readability and keyboard-visible focus states.

## Responsive Behavior

- Desktop page mode uses a narrow session rail and a flexible conversation pane.
- On smaller screens, the session rail becomes a compact top section or collapsible area while the conversation and composer remain primary.
- Floating mode remains width-resizable and does not inherit desktop-only grid assumptions.

## Verification

- Update source-level chat experience tests to assert removal of duplicate account/assistant UI and presence of the new session rail, conversation header, prompt cards, and button classes.
- Run the focused chat test, the complete UI test suite, and the production build.
- Verify page mode and floating mode in the browser at desktop and narrow widths, including new session, session switch, upload trigger, prompt submission, composer focus, and disabled states.
- Compare the browser render against the approved visual mockup and correct material spacing, typography, color, button, and responsive differences before handoff.

## Assumptions

- The global application header remains the sole account surface and is outside this change.
- Workspace statistics remain available elsewhere in the product and do not need a replacement inside chat.
- No API, database, authentication, or conversation schema changes are required.
