// DND HR-Civ HR Policy Advisory System
// Client-side application logic

(function() {
    'use strict';

    const API_BASE = '';
    const ENABLE_WEBSOCKET = false;
    let ws = null;
    let wsReady = false;
    let preferPolling = true;
    let reconnectTimer = null;
    let pollingTimer = null;
    let currentQueryId = null;
    let pendingFeedback = null;

    // DOM elements
    const chatHistory = document.getElementById('chatHistory');
    const queryInput = document.getElementById('queryInput');
    const sendButton = document.getElementById('sendButton');
    const agentList = document.getElementById('agentList');
    const citationList = document.getElementById('citationList');
    const feedbackContent = document.getElementById('feedbackContent');
    const progressBarArea = document.getElementById('progressBarArea');
    const progressStatusText = document.getElementById('progressStatusText');
    const liveStatus = document.getElementById('liveStatus');
    const queryForm = document.getElementById('queryForm');

    const AGENT_DISPLAY_NAMES = {
        orchestrator: 'Orchestrator',
        staffing: 'Staffing & Recruitment',
        classification: 'Classification & Compensation',
        labour: 'Labour Relations',
        learning: 'Learning & Performance',
        equity: 'Equity, Diversity & Inclusion',
        ohs: 'Health, Safety & Wellness',
        languages: 'Official Languages',
        governance: 'Values, Ethics & Governance',
    };

    function showProgress(text) {
        progressStatusText.textContent = text;
        progressBarArea.hidden = false;
        announce(text);
    }

    function hideProgress() {
        progressBarArea.hidden = true;
        progressStatusText.textContent = '';
    }

    function announce(text) {
        if (liveStatus) {
            liveStatus.textContent = text;
        }
    }

    // Initialize
    document.addEventListener('DOMContentLoaded', init);

    function init() {
        setupEventListeners();
        sendButton.disabled = queryInput.value.trim().length === 0;
        if (ENABLE_WEBSOCKET) {
            connectWebSocket();
        }
    }

    function setupEventListeners() {
        queryForm.addEventListener('submit', (e) => {
            e.preventDefault();
            submitQuery();
        });
        
        queryInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitQuery();
            }
        });

        queryInput.addEventListener('input', () => {
            const hasText = queryInput.value.trim().length > 0;
            sendButton.disabled = !hasText || isProcessing();
        });

        // submitFeedback listener is wired in showFeedbackControls() after the element is created
    }

    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}`;
        
        ws = new WebSocket(wsUrl + '/ws');

        ws.onopen = () => {
            console.log('WebSocket connected');
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleMessage(data);
            } catch (e) {
                console.error('Failed to parse WebSocket message:', e);
            }
        };

        ws.onclose = () => {
            console.log('WebSocket disconnected');
            wsReady = false;
            preferPolling = true;
            if (!reconnectTimer) {
                reconnectTimer = setTimeout(() => {
                    reconnectTimer = null;
                    connectWebSocket();
                }, 10000);
            }
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            wsReady = false;
            preferPolling = true;
        };
    }

    function handleMessage(data) {
        // agent_status_update messages carry no query_id — always pass them through.
        // All other messages are filtered to the active query.
        if (data.type !== 'agent_status_update' && data.type !== 'session_welcome' && data.type !== 'user_query') {
            if (!currentQueryId || currentQueryId !== data.query_id) return;
        }

        switch (data.type) {
            case 'user_query':
                handleUserQueryMessage(data);
                break;
            case 'agent_status_update':
                handleAgentStatusUpdate(data);
                break;
            case 'response_chunk':
                handleResponseChunk(data);
                break;
            case 'response_complete':
                handleResponseComplete(data);
                break;
            case 'error':
                handleError(data);
                break;
            case 'session_welcome':
                wsReady = true;
                console.log('Session initialized');
                break;
        }
    }

    function handleUserQueryMessage(data) {
        currentQueryId = data.query_id;
        
        // Clear welcome message if present
        const welcomeMsg = chatHistory.querySelector('.welcome-message');
        if (welcomeMsg) {
            welcomeMsg.style.display = 'none';
        }

        // Add user message
        const userMessage = createMessage('user', data.query_text);
        chatHistory.appendChild(userMessage);
        scrollToBottom();
    }

    function handleAgentStatusUpdate(data) {
        const agentItem = agentList.querySelector(`[data-agent="${data.agent_id}"]`);
        if (agentItem) {
            const statusDot = agentItem.querySelector('.status-dot');
            const statusText = agentItem.querySelector('.agent-status-text');
            statusDot.setAttribute('data-status', data.status);
            statusText.textContent = formatStatus(data.status);
        }

        if (data.status === 'working') {
            const name = AGENT_DISPLAY_NAMES[data.agent_id] || data.agent_id;
            if (data.agent_id === 'orchestrator') {
                showProgress('Orchestrator analysing query and selecting specialist agents\u2026 (may take up to a minute)');
            } else {
                showProgress(`${name} agent reviewing policy instruments\u2026`);
            }
        } else if (data.status === 'complete' && data.agent_id === 'orchestrator') {
            // Orchestrator finishing means synthesis is done — hideProgress() is
            // called in handleResponseComplete; nothing to do here.
        } else if (data.status === 'complete') {
            // A specialist finished — check if orchestrator is still going
            const orchestratorDot = agentList.querySelector('[data-agent="orchestrator"] .status-dot');
            const orchestratorWorking = orchestratorDot &&
                orchestratorDot.getAttribute('data-status') === 'working';
            if (!orchestratorWorking) {
                showProgress('Synthesising response from specialist findings\u2026');
            }
        }
    }

    function handleResponseChunk(data) {
        let messageEl = chatHistory.querySelector('.message.system:last-of-type');
        
        if (!messageEl) {
            messageEl = createMessage('system', '', currentQueryId);
            chatHistory.appendChild(messageEl);
        }

        const textEl = messageEl.querySelector('.message-text');
        textEl.textContent += data.chunk;
        scrollToBottom();
    }

    function handleResponseComplete(data) {
        let messageEl = chatHistory.querySelector('.message.system:last-of-type');

        if (!messageEl) {
            messageEl = createMessage('system', '', currentQueryId);
            chatHistory.appendChild(messageEl);
        }

        try {
            const resp = data.orchestrator_response;
            const textEl = messageEl.querySelector('.message-text');

            if (resp && textEl) {
                renderResponseText(textEl, resp);
            }

            renderCitations((data.orchestrator_response && data.orchestrator_response.citations) ? data.orchestrator_response.citations : []);
            showFeedbackControls(currentQueryId);
            announce('Response complete. Policy citations and feedback controls are now available.');
            scrollToBottom();
        } catch (err) {
            console.error('Error rendering response:', err);
        } finally {
            hideProgress();
            resetProcessingState();
        }
    }

    function handleError(data) {
        const messageEl = createMessage('system', `Error: ${data.message}`, currentQueryId);
        chatHistory.appendChild(messageEl);
        scrollToBottom();
        hideProgress();
        resetProcessingState();
        announce(`Error processing query. ${data.message}`);
    }

    function submitQuery() {
        const queryText = queryInput.value.trim();
        if (!queryText || isProcessing()) return;

        queryInput.value = '';
        queryInput.disabled = true;
        sendButton.disabled = true;

        // Reset agent dots to idle before each new query
        agentList.querySelectorAll('.status-dot').forEach(dot => {
            dot.setAttribute('data-status', 'idle');
        });
        agentList.querySelectorAll('.agent-status-text').forEach(text => {
            text.textContent = 'Idle';
        });

        if (canUseWebSocket()) {
            ws.send(JSON.stringify({
                type: 'query_start',
                query_text: queryText,
            }));
        } else {
            startPollingQuery(queryText);
        }
        showProgress('Routing query to specialist agents\u2026');
    }

    function canUseWebSocket() {
        return !preferPolling && wsReady && ws && ws.readyState === WebSocket.OPEN;
    }

    function startPollingQuery(queryText) {
        fetch(`${API_BASE}/api/query/start`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ query_text: queryText }),
        })
        .then(res => {
            if (!res.ok) {
                throw new Error(`Query start failed with HTTP ${res.status}`);
            }
            return res.json();
        })
        .then(data => {
            currentQueryId = data.query_id;
            handleUserQueryMessage({
                type: 'user_query',
                query_id: data.query_id,
                query_text: queryText,
            });
            pollQueryStatus(data.query_id);
        })
        .catch(err => {
            handleError({
                query_id: currentQueryId,
                message: err.message || 'Unable to start query.',
            });
        });
    }

    function pollQueryStatus(queryId) {
        clearPollingTimer();
        fetch(`${API_BASE}/api/query/${queryId}/status`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
            },
        })
        .then(res => {
            if (!res.ok) {
                throw new Error(`Query status failed with HTTP ${res.status}`);
            }
            return res.json();
        })
        .then(job => {
            Object.values(job.agent_statuses || {}).forEach(handleAgentStatusUpdate);

            if (job.status === 'complete') {
                handleResponseComplete({
                    type: 'response_complete',
                    query_id: queryId,
                    orchestrator_response: job.orchestrator_response,
                    processing_time_ms: job.processing_time_ms,
                });
                return;
            }

            if (job.status === 'error') {
                handleError({
                    query_id: queryId,
                    message: job.error || 'Query failed.',
                });
                return;
            }

            pollingTimer = setTimeout(() => pollQueryStatus(queryId), 2500);
        })
        .catch(err => {
            pollingTimer = setTimeout(() => pollQueryStatus(queryId), 5000);
            console.error('Polling query status failed:', err);
        });
    }

    function clearPollingTimer() {
        if (pollingTimer) {
            clearTimeout(pollingTimer);
            pollingTimer = null;
        }
    }

    function createMessage(type, text = '', queryId = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}`;
        
        if (type === 'system') {
            messageDiv.dataset.queryId = queryId;
            
            const headers = document.createElement('div');
            headers.className = 'message-header';
            const badge = document.createElement('span');
            badge.className = 'agent-badge';
            badge.textContent = 'Orchestrator';
            const time = document.createElement('span');
            time.className = 'message-time';
            time.textContent = formatTime(new Date());
            headers.appendChild(badge);
            headers.appendChild(time);
            
            const textDiv = document.createElement('div');
            textDiv.className = 'message-text';
            textDiv.textContent = text;
            
            messageDiv.appendChild(headers);
            messageDiv.appendChild(textDiv);
        } else {
            messageDiv.textContent = text;
        }
        
        return messageDiv;
    }

    function renderResponseText(textEl, response) {
        textEl.textContent = '';

        if (response.summary) {
            renderMarkdownInto(textEl, response.summary);
        }

        if (response.detailed_analysis) {
            const detail = document.createElement('div');
            detail.className = 'response-detail';
            renderMarkdownInto(detail, response.detailed_analysis);
            textEl.appendChild(detail);
        }

        if (!response.summary && !response.detailed_analysis) {
            const empty = document.createElement('p');
            const emphasis = document.createElement('em');
            emphasis.textContent = 'Response received but contained no text.';
            empty.appendChild(emphasis);
            textEl.appendChild(empty);
        }
    }

    function renderMarkdownInto(container, markdown) {
        const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n');
        let paragraphLines = [];
        let list = null;

        function flushParagraph() {
            if (paragraphLines.length === 0) return;
            const p = document.createElement('p');
            p.textContent = paragraphLines.join(' ');
            container.appendChild(p);
            paragraphLines = [];
        }

        function flushList() {
            if (!list) return;
            container.appendChild(list);
            list = null;
        }

        lines.forEach(rawLine => {
            const line = rawLine.trim();
            if (!line) {
                flushParagraph();
                flushList();
                return;
            }

            const heading = line.match(/^#{1,4}\s+(.+)$/);
            if (heading) {
                flushParagraph();
                flushList();
                const h = document.createElement('h3');
                h.textContent = heading[1];
                container.appendChild(h);
                return;
            }

            const bullet = line.match(/^[-*]\s+(.+)$/);
            if (bullet) {
                flushParagraph();
                if (!list) {
                    list = document.createElement('ul');
                }
                const li = document.createElement('li');
                li.textContent = bullet[1];
                list.appendChild(li);
                return;
            }

            flushList();
            paragraphLines.push(line);
        });

        flushParagraph();
        flushList();
    }

    function renderCitations(citations) {
        citationList.innerHTML = '';
        
        if (citations && citations.length > 0) {
            const groupedByAgent = {};
            citations.forEach(citation => {
                const agentId = citation.sourced_from_agent || 'general';
                if (!groupedByAgent[agentId]) {
                    groupedByAgent[agentId] = [];
                }
                groupedByAgent[agentId].push(citation);
            });

            const agentNames = {
                'staffing': 'Staffing & Recruitment',
                'classification': 'Classification & Compensation',
                'labour': 'Labour Relations',
                'learning': 'Learning & Performance',
                'equity': 'Equity, Diversity & Inclusion',
                'ohs': 'Health, Safety & Wellness',
                'languages': 'Official Languages',
                'governance': 'Values, Ethics & Governance',
                'general': 'General'
            };

            Object.entries(groupedByAgent).forEach(([agentId, agentCitations]) => {
                const groupDiv = document.createElement('div');
                const heading = document.createElement('p');
                heading.className = 'citation-agent-heading';
                heading.textContent = agentNames[agentId] || agentId;
                const citationGroup = document.createElement('div');
                citationGroup.className = 'citation-group';

                agentCitations.forEach(citation => {
                    const item = document.createElement('div');
                    item.className = 'citation-item';

                    const title = document.createElement('div');
                    title.className = 'citation-item-title';
                    if (citation.url) {
                        const link = document.createElement('a');
                        link.href = citation.url;
                        link.target = '_blank';
                        link.rel = 'noopener noreferrer';
                        link.textContent = citation.instrument_title || 'Untitled instrument';
                        title.appendChild(link);
                    } else {
                        title.textContent = citation.instrument_title || 'Untitled instrument';
                    }

                    const type = document.createElement('div');
                    type.className = 'citation-type';
                    type.textContent = citation.instrument_type || 'Policy instrument';

                    item.appendChild(title);
                    item.appendChild(type);

                    if (citation.relevant_section) {
                        const section = document.createElement('div');
                        section.className = 'citation-section';
                        section.textContent = `Section: ${citation.relevant_section}`;
                        item.appendChild(section);
                    }

                    citationGroup.appendChild(item);
                });

                groupDiv.appendChild(heading);
                groupDiv.appendChild(citationGroup);
                citationList.appendChild(groupDiv);
            });
        } else {
            const placeholder = document.createElement('p');
            placeholder.className = 'citation-placeholder';
            placeholder.textContent = 'No citations available for this response.';
            citationList.appendChild(placeholder);
        }
    }

    function showFeedbackControls(queryId) {
        pendingFeedback = queryId;
        
        feedbackContent.innerHTML = `
            <div class="feedback-controls">
                <fieldset class="feedback-rating">
                    <legend>How accurate was this response?</legend>
                    <div class="feedback-buttons">
                        <button type="button" class="btn-feedback accurate" data-rating="accurate" aria-pressed="false">Accurate</button>
                        <button type="button" class="btn-feedback needs-work" data-rating="needs-work" aria-pressed="false">Needs Work</button>
                    </div>
                </fieldset>
                <p class="feedback-error" id="feedbackError" tabindex="-1" hidden>Please select Accurate or Needs Work.</p>
                <div class="feedback-comment">
                    <label for="feedbackComment">Optional improvement note</label>
                    <textarea id="feedbackComment" placeholder="Tell us how we can improve. Press Shift+Enter for a new line."></textarea>
                    <button type="button" class="btn-submit-feedback" id="submitFeedback">Submit Feedback</button>
                </div>
            </div>
        `;

        // Wire up feedback buttons
        document.querySelectorAll('.feedback-buttons .btn-feedback').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.feedback-buttons .btn-feedback').forEach(b => {
                    b.classList.remove('selected');
                    b.setAttribute('aria-pressed', 'false');
                });
                btn.classList.add('selected');
                btn.setAttribute('aria-pressed', 'true');
                const error = document.getElementById('feedbackError');
                if (error) {
                    error.hidden = true;
                }
            });
        });

        // Wire up submit button now that the element exists in the DOM
        const submitBtn = document.getElementById('submitFeedback');
        if (submitBtn) {
            submitBtn.addEventListener('click', submitFeedback);
        }

        const textarea = feedbackContent.querySelector('textarea');
        if (textarea) {
            textarea.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    document.getElementById('submitFeedback').click();
                }
            });
        }
    }

    function submitFeedback() {
        const rating = document.querySelector('.feedback-buttons .btn-feedback.selected')?.getAttribute('data-rating');
        const commentEl = feedbackContent.querySelector('textarea');
        const comment = commentEl ? commentEl.value.trim() : null;

        if (!rating) {
            const error = document.getElementById('feedbackError');
            if (error) {
                error.hidden = false;
                error.focus();
            }
            announce('Please select Accurate or Needs Work before submitting feedback.');
            return;
        }

        fetch(`${API_BASE}/api/feedback`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                feedback_id: generateId(),
                query_id: pendingFeedback,
                rating: rating,
                comment: comment,
            }),
        })
        .then(res => res.json())
        .then(data => {
            showFeedbackThankYou();
        })
        .catch(err => {
            console.error('Failed to submit feedback:', err);
            announce('Failed to submit feedback. Please try again.');
        });
    }

    function showFeedbackThankYou() {
        feedbackContent.innerHTML = `
            <p class="feedback-thanks" tabindex="-1">
                Thank you for your feedback. This helps improve the system.
            </p>
        `;
        const thanks = feedbackContent.querySelector('.feedback-thanks');
        if (thanks) {
            thanks.focus();
        }
        announce('Thank you for your feedback.');
        pendingFeedback = null;
    }

    function formatTime(date) {
        return date.toLocaleTimeString('en-CA', { hour: '2-digit', minute: '2-digit' });
    }

    function scrollToBottom() {
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function isProcessing() {
        return !!currentQueryId && 
               agentList.querySelector('.status-dot[data-status="working"]') !== null;
    }

    function resetProcessingState() {
        clearPollingTimer();
        currentQueryId = null;
        queryInput.disabled = false;
        queryInput.focus();
        sendButton.disabled = queryInput.value.trim().length === 0;
    }

    function formatStatus(status) {
        const labels = {
            idle: 'Idle',
            working: 'Working',
            complete: 'Complete',
            error: 'Error',
        };
        return labels[status] || status;
    }

    function generateId() {
        return 'fb_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }
})();
