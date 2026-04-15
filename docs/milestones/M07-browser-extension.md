# M7: Browser Extension

> Capture conversations from web-based AI tools (ChatGPT, Claude, Gemini, Perplexity).

**Prerequisites:** M3 (REST API)
**Estimated complexity:** Medium
**Can run in parallel with:** M6 (Dashboard), M8 (Cloud)
**Exit criteria:** Extension captures from 4 web AI tools, sends to Memgentic API, published on Chrome Web Store.

---

## Phase 7.1: Plasmo Project Setup

**Goal:** Initialize browser extension project with Plasmo framework.

### Tasks

1. **Create extension project:**
   ```bash
   npm create plasmo -- --with-src extension
   cd extension
   npm install
   ```

2. **Configure for Chrome + Firefox:**
   ```json
   // package.json
   {
     "name": "mneme-extension",
     "displayName": "Memgentic — AI Memory",
     "version": "0.1.0",
     "description": "Capture knowledge from AI conversations automatically",
     "manifest": {
       "permissions": ["storage", "activeTab"],
       "host_permissions": [
         "https://chat.openai.com/*",
         "https://chatgpt.com/*",
         "https://claude.ai/*",
         "https://gemini.google.com/*",
         "https://www.perplexity.ai/*"
       ]
     }
   }
   ```

3. **Create shared utilities:**
   - API client for communicating with Memgentic REST API
   - Conversation extraction helpers
   - Storage helpers (chrome.storage.sync for settings)

4. **Project structure:**
   ```
   extension/src/
   ├── contents/
   │   ├── chatgpt.ts          # ChatGPT content script
   │   ├── claude.ts           # Claude web content script
   │   ├── gemini.ts           # Gemini content script
   │   └── perplexity.ts       # Perplexity content script
   ├── background/
   │   └── index.ts            # Service worker (batching, API calls)
   ├── popup/
   │   └── index.tsx           # Extension popup UI
   ├── options/
   │   └── index.tsx           # Settings page
   └── lib/
       ├── api.ts              # Memgentic API client
       ├── extractor.ts        # Common extraction helpers
       └── storage.ts          # Extension settings
   ```

### Acceptance Criteria
- [ ] Extension loads in Chrome
- [ ] Can build for Chrome and Firefox
- [ ] Basic popup displays

---

## Phase 7.2: ChatGPT Content Script

**Goal:** Capture conversations from chat.openai.com / chatgpt.com.

### Tasks

1. **DOM observation strategy:**
   - Use MutationObserver on the conversation container
   - Detect when new messages appear
   - Extract user and assistant messages from DOM nodes

2. **Conversation extraction:**
   - Extract message text content
   - Identify message role (user/assistant)
   - Get conversation title from page header
   - Handle streaming (wait for completion)

3. **Debounce and batch:**
   - Wait for conversation to stabilize (no new messages for 30s)
   - Batch all messages from the session
   - Send to background service worker

4. **Handle page changes:**
   - Detect conversation switches
   - Clean up observer on navigation

### Acceptance Criteria
- [ ] Captures ChatGPT conversations in real-time
- [ ] Handles streaming messages correctly
- [ ] Sends complete exchanges to background worker

---

## Phase 7.3: Claude Web Content Script

**Goal:** Capture conversations from claude.ai.

### Tasks

1. **Similar approach to ChatGPT:**
   - MutationObserver on conversation container
   - Claude's DOM structure is different — research selectors
   - Extract user/assistant messages
   - Handle artifacts and thinking blocks

2. **Claude-specific handling:**
   - Ignore tool use blocks (or capture metadata only)
   - Handle long responses with "Continue" buttons
   - Capture conversation title from sidebar

### Acceptance Criteria
- [ ] Captures Claude web conversations
- [ ] Handles Claude-specific UI elements
- [ ] Correctly identifies user vs assistant turns

---

## Phase 7.4: Gemini Web Content Script

**Goal:** Capture conversations from gemini.google.com.

### Tasks

1. **Gemini-specific DOM observation:**
   - Different DOM structure from ChatGPT/Claude
   - Handle multi-modal responses (text only, skip images)
   - Extract conversation turns

### Acceptance Criteria
- [ ] Captures Gemini web conversations
- [ ] Text extraction works correctly

---

## Phase 7.5: Perplexity Content Script

**Goal:** Capture from perplexity.ai.

### Tasks

1. **Perplexity has unique structure:**
   - Search-style UI with follow-up questions
   - Sources/citations in responses
   - Extract query + answer + sources

### Acceptance Criteria
- [ ] Captures Perplexity searches and answers
- [ ] Preserves source citations

---

## Phase 7.6: Extension Popup

**Goal:** Status display, recent captures, quick search.

### Tasks

1. **Popup UI (React + Tailwind):**
   - Connection status (connected to Memgentic at localhost:8100)
   - Recent captures list (last 5)
   - Quick search input
   - Link to dashboard
   - Capture toggle (on/off)

2. **Show capture count per site**

### Acceptance Criteria
- [ ] Popup shows connection status
- [ ] Recent captures displayed
- [ ] Capture toggle works

---

## Phase 7.7: Options Page

**Goal:** Extension configuration.

### Tasks

1. **Settings:**
   - Memgentic API URL (default: localhost:8100)
   - API key (for cloud mode)
   - Per-site capture toggle (ChatGPT on/off, Claude on/off, etc.)
   - Capture delay (seconds to wait before sending)
   - Auto-capture vs manual mode

2. **Store settings in chrome.storage.sync**

### Acceptance Criteria
- [ ] All settings configurable
- [ ] Settings persist across browser restarts
- [ ] Settings sync across Chrome instances

---

## Phase 7.8: Background Service Worker

**Goal:** Batch processing and API communication.

### Tasks

1. **Receive messages from content scripts**
2. **Batch and deduplicate** (same conversation, updated)
3. **Send to Memgentic API** with proper source metadata:
   ```json
   {
     "content": "...",
     "platform": "chatgpt",
     "capture_method": "browser_extension",
     "session_title": "React Architecture Discussion"
   }
   ```
4. **Retry on API failure** (queue + exponential backoff)
5. **Show badge count** of pending/recent captures

### Acceptance Criteria
- [ ] Messages batched and sent to API
- [ ] Retry on failure
- [ ] Badge shows capture count

---

## Phase 7.9: Store Submission

**Goal:** Publish to Chrome Web Store and Firefox Add-ons.

### Tasks

1. **Chrome Web Store:**
   - Create developer account
   - Prepare screenshots, description, icons
   - Submit for review

2. **Firefox Add-ons:**
   - Build Firefox version with Plasmo
   - Submit to addons.mozilla.org

3. **Create extension landing page** (or section on main site)

### Acceptance Criteria
- [ ] Extension published on Chrome Web Store
- [ ] Extension published on Firefox Add-ons
- [ ] Installation instructions in docs
