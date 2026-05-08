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
    }

    function hideProgress() {
        progressBarArea.hidden = true;
        progressStatusText.textContent = '';
    }

    // Initialize
    document.addEventListener('DOMContentLoaded', init);

    function init() {
        setupEventListeners();
        if (ENABLE_WEBSOCKET) {
            connectWebSocket();
        }
    }

    function setupEventListeners() {
        sendButton.addEventListener('click', submitQuery);
        
        queryInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitQuery();
            }
        });

        queryInput.addEventListener('input', () => {
            const hasText = queryInput.value.trim().length > 0;
            sendButton.disabled = !hasText || isProcessing();
            sendButton.style.opacity = hasText && !isProcessing() ? '1' : '0.6';
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
            statusDot.setAttribute('data-status', data.status);
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
                let html = '';
                if (resp.summary) {
                    html += `<p>${resp.summary}</p>`;
                }
                if (resp.detailed_analysis) {
                    html += `<p style="margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border);">${resp.detailed_analysis}</p>`;
                }
                textEl.innerHTML = html || '<p><em>Response received but contained no text.</em></p>';
            }

            renderCitations((data.orchestrator_response && data.orchestrator_response.citations) ? data.orchestrator_response.citations : []);
            showFeedbackControls(currentQueryId);
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
            headers.innerHTML = `
                <span class="agent-badge">Orchestrator</span>
                <span class="message-time">${formatTime(new Date())}</span>
            `;
            
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

    function updateMessageWithMetadata(messageEl, response) {
        const textEl = messageEl.querySelector('.message-text');
        const agentBadges = messageEl.querySelector('.agent-badges');
        const footer = messageEl.querySelector('.message-footer');

        // Update main text
        if (response.summary) {
            textEl.innerHTML = wrapWithCitations(response.summary, response.citations || []);
        }

        if (response.detailed_analysis) {
            textEl.innerHTML += `<p style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border);">${response.detailed_analysis}</p>`;
        }

        // Update agent badges
        if (response.agents_consulted && response.agents_consulted.length > 0 && agentBadges) {
            const badgeNames = {
                'staffing': 'Staffing',
                'classification': 'Classification',
                'labour': 'Labour',
                'learning': 'Learning',
                'equity': 'Equity',
                'ohs': 'Safety',
                'languages': 'Languages',
                'governance': 'Governance'
            };
            agentBadges.innerHTML = response.agents_consulted
                .map(id => `<span class="agent-badge">${badgeNames[id] || id}</span>`)
                .join('');
        }

        // Update confidence badge
        if (footer) {
            const newFooter = document.createElement('div');
            newFooter.className = 'message-footer';
            const confidenceClass = `confidence-${(response.overall_confidence || 'medium').toLowerCase()}`;
            newFooter.innerHTML = `
                <span class="confidence-badge ${confidenceClass}">${response.overall_confidence || 'medium'} confidence</span>
            `;
            messageEl.appendChild(newFooter);
        }
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
                groupDiv.innerHTML = `
                    <p style="font-family: 'Calibri', sans-serif; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-light); margin-bottom: 0.5rem;">
                        ${agentNames[agentId] || agentId}
                    </p>
                    <div style="display: flex; flex-direction: column; gap: 0.5rem;">
                        ${agentCitations.map(citation => `
                            <div class="citation-item">
                                <div class="citation-item-title">
                                    ${citation.url
                                        ? `<a href="${citation.url}" target="_blank" rel="noopener noreferrer">${citation.instrument_title}</a>`
                                        : citation.instrument_title}
                                </div>
                                <div class="citation-type">${citation.instrument_type}</div>
                                ${citation.relevant_section ? `<div class="citation-section">Section: ${citation.relevant_section}</div>` : ''}
                            </div>
                        `).join('')}
                    </div>
                `;
                citationList.appendChild(groupDiv);
            });
        } else {
            citationList.innerHTML = '<p class="citation-placeholder">No citations available for this response.</p>';
        }
    }

    function showFeedbackControls(queryId) {
        pendingFeedback = queryId;
        
        feedbackContent.innerHTML = `
            <div class="feedback-controls">
                <p style="font-family: 'Calibri', sans-serif; font-size: 0.8rem; color: var(--text); margin-bottom: 0.5rem;">
                    How accurate was this response?
                </p>
                <div class="feedback-buttons">
                    <button class="btn-feedback accurate" data-rating="accurate">✓ Accurate</button>
                    <button class="btn-feedback needs-work" data-rating="needs-work">⚠ Needs Work</button>
                </div>
                <div class="feedback-comment">
                    <textarea placeholder="Optional: Tell us how we can improve... (press Enter to submit)"></textarea>
                    <button class="btn-submit-feedback" id="submitFeedback">Submit Feedback</button>
                </div>
            </div>
        `;

        // Wire up feedback buttons
        document.querySelectorAll('.feedback-buttons .btn-feedback').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.feedback-buttons .btn-feedback').forEach(b => {
                    b.classList.remove('selected');
                    b.style.opacity = '0.5';
                    b.disabled = true;
                });
                btn.classList.add('selected');
                btn.style.opacity = '1';
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
            alert('Please select "Accurate" or "Needs Work"');
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
            alert('Failed to submit feedback. Please try again.');
        });
    }

    function showFeedbackThankYou() {
        feedbackContent.innerHTML = `
            <p style="font-family: 'Calibri', sans-serif; font-size: 0.85rem; color: var(--green); text-align: center; padding: 1rem;">
                Thank you for your feedback. This helps improve the system.
            </p>
        `;
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
        sendButton.disabled = false;
        sendButton.style.opacity = '1';
    }

    function wrapWithCitations(text, citations) {
        let result = text;
        citations.forEach((citation, index) => {
            const marker = `<sup class="citation-marker" title="${citation.instrument_title}">${index + 1}</sup>`;
            const search = citation.instrument_title.split(' ').slice(0, 3).join('');
            result = result.replace(
                new RegExp(`(${search.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[\\s\\S]*?)`, 'gi'),
                `$1${marker}`
            );
        });
        return result;
    }

    function showError(message) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'message system error';
        errorDiv.innerHTML = `<p style="color: var(--error);">${message}</p>`;
        chatHistory.appendChild(errorDiv);
        scrollToBottom();
        resetProcessingState();
    }

    function generateId() {
        return 'fb_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }
})();
