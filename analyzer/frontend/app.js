// MoltNet Analyzer Frontend Application

const API_BASE = '';

// State
let state = {
    currentRun: null,
    runs: [],
    conversations: [],
    convPage: 0,
    convLimit: 20,
    reflectionType: '',
    charts: {}
};

// DOM Elements
const elements = {
    runSelect: document.getElementById('run-select'),
    navBtns: document.querySelectorAll('.nav-btn'),
    views: document.querySelectorAll('.view'),
    modal: document.getElementById('conv-modal'),
};

// ==================== Initialization ====================

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initModal();
    initConversationSearch();
    initReflectionFilters();
    loadRuns();
});

function initNavigation() {
    elements.navBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            switchView(view);
        });
    });

    elements.runSelect.addEventListener('change', () => {
        state.currentRun = elements.runSelect.value;
        if (state.currentRun) {
            loadCurrentView();
        }
    });
}

function switchView(viewId) {
    elements.navBtns.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === viewId);
    });
    elements.views.forEach(view => {
        view.classList.toggle('active', view.id === `${viewId}-view`);
    });
    loadCurrentView();
}

function loadCurrentView() {
    if (!state.currentRun) return;

    const activeView = document.querySelector('.view.active');
    if (!activeView) return;

    const viewId = activeView.id.replace('-view', '');
    switch (viewId) {
        case 'timeline':
            loadTimeline();
            break;
        case 'family-tree':
            loadFamilyTree();
            break;
        case 'metrics':
            loadMetrics();
            break;
        case 'conversations':
            loadConversations();
            break;
        case 'reflections':
            loadReflections();
            break;
    }
}

// ==================== API Calls ====================

async function api(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, options);
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

async function loadRuns() {
    try {
        const data = await api('/api/runs');
        state.runs = data.runs;

        elements.runSelect.innerHTML = '<option value="">Select a run...</option>';
        data.runs.forEach(run => {
            const option = document.createElement('option');
            option.value = run.run_id;
            const date = run.started_at ? new Date(run.started_at * 1000).toLocaleString() : 'Unknown';
            option.textContent = `${run.run_id} (${run.status})`;
            elements.runSelect.appendChild(option);
        });

        // Auto-select first run
        if (data.runs.length > 0) {
            elements.runSelect.value = data.runs[0].run_id;
            state.currentRun = data.runs[0].run_id;
            loadCurrentView();
        }
    } catch (error) {
        console.error('Failed to load runs:', error);
    }
}

// ==================== Timeline ====================

async function loadTimeline() {
    const container = document.getElementById('timeline-chart');
    container.innerHTML = '<div class="loading">Loading timeline...</div>';

    try {
        const data = await api(`/api/runs/${state.currentRun}/timeline`);
        renderTimeline(data, container);
    } catch (error) {
        container.innerHTML = '<div class="empty-state"><h3>No timeline data available</h3></div>';
    }
}

function renderTimeline(data, container) {
    if (!data.entries || data.entries.length === 0) {
        container.innerHTML = '<div class="empty-state"><h3>No bots in this run</h3></div>';
        return;
    }

    const startTime = data.start_time || Math.min(...data.entries.map(e => e.birth_time || 0));
    const endTime = data.end_time || Math.max(...data.entries.map(e => e.death_time || e.birth_time || 0));
    const duration = endTime - startTime || 1;

    const html = `
        <div class="timeline-gantt">
            ${data.entries.map((entry, i) => {
                const birthOffset = ((entry.birth_time || startTime) - startTime) / duration * 100;
                const width = ((entry.death_time || endTime) - (entry.birth_time || startTime)) / duration * 100;
                const modelClass = getModelClass(entry.model);

                return `
                    <div class="timeline-row" style="margin-bottom: 4px;">
                        <div class="timeline-label" style="display: inline-block; width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--text-secondary);">
                            ${entry.bot_name}
                        </div>
                        <div style="display: inline-block; width: calc(100% - 160px); position: relative; height: 24px; background: var(--bg-tertiary); border-radius: 4px;">
                            <div class="timeline-bar ${modelClass}"
                                 style="position: absolute; left: ${birthOffset}%; width: ${Math.max(width, 1)}%; height: 100%;"
                                 title="${entry.bot_name}&#10;Model: ${entry.model || 'Unknown'}&#10;Cycles: ${entry.cycles_lived || 0}&#10;Success: ${((entry.success_rate || 0) * 100).toFixed(1)}%&#10;Death: ${entry.death_cause || 'alive'}">
                            </div>
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
    `;

    container.innerHTML = html;
}

function getModelClass(model) {
    if (!model) return 'other';
    const m = model.toLowerCase();
    if (m.includes('claude') || m.includes('opus') || m.includes('sonnet')) return 'claude';
    if (m.includes('cerebras') || m.includes('glm') || m.includes('zai')) return 'cerebras';
    return 'other';
}

// ==================== Family Tree ====================

async function loadFamilyTree() {
    const container = document.getElementById('family-tree-chart');
    container.innerHTML = '<div class="loading">Loading family tree...</div>';

    try {
        const data = await api(`/api/runs/${state.currentRun}/family-tree`);
        renderFamilyTree(data, container);
    } catch (error) {
        container.innerHTML = '<div class="empty-state"><h3>No family tree data available</h3></div>';
    }
}

function renderFamilyTree(data, container) {
    if (!data.nodes || data.nodes.length === 0) {
        container.innerHTML = '<div class="empty-state"><h3>No bots in this run</h3></div>';
        return;
    }

    container.innerHTML = '';

    const width = container.clientWidth;
    const height = 600;

    const svg = d3.select(container)
        .append('svg')
        .attr('width', width)
        .attr('height', height);

    // Create force simulation
    const simulation = d3.forceSimulation(data.nodes)
        .force('link', d3.forceLink(data.edges).id(d => d.id).distance(80))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(30));

    // Draw links
    const link = svg.append('g')
        .selectAll('line')
        .data(data.edges)
        .enter()
        .append('line')
        .attr('class', 'tree-link');

    // Draw nodes
    const node = svg.append('g')
        .selectAll('g')
        .data(data.nodes)
        .enter()
        .append('g')
        .attr('class', d => `tree-node ${d.death_cause ? 'dead' : ''}`)
        .call(d3.drag()
            .on('start', dragstarted)
            .on('drag', dragged)
            .on('end', dragended));

    node.append('circle')
        .attr('r', d => Math.max(8, Math.min(20, (d.cycles_lived || 10) / 10)))
        .attr('fill', d => getModelColor(d.model))
        .attr('stroke', d => d.death_cause ? '#666' : getModelColor(d.model));

    node.append('text')
        .attr('dx', 15)
        .attr('dy', 4)
        .text(d => d.id.length > 15 ? d.id.substring(0, 15) + '...' : d.id);

    node.append('title')
        .text(d => `${d.id}\nModel: ${d.model || 'Unknown'}\nGen: ${d.generation}\nCycles: ${d.cycles_lived || 0}\nChildren: ${d.children_spawned || 0}`);

    simulation.on('tick', () => {
        link
            .attr('x1', d => d.source.x)
            .attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x)
            .attr('y2', d => d.target.y);

        node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    function dragstarted(event) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        event.subject.fx = event.subject.x;
        event.subject.fy = event.subject.y;
    }

    function dragged(event) {
        event.subject.fx = event.x;
        event.subject.fy = event.y;
    }

    function dragended(event) {
        if (!event.active) simulation.alphaTarget(0);
        event.subject.fx = null;
        event.subject.fy = null;
    }

    // Reset button
    document.getElementById('tree-reset').onclick = () => {
        simulation.alpha(1).restart();
    };
}

function getModelColor(model) {
    if (!model) return '#a371f7';
    const m = model.toLowerCase();
    if (m.includes('claude') || m.includes('opus') || m.includes('sonnet')) return '#58a6ff';
    if (m.includes('cerebras') || m.includes('glm') || m.includes('zai')) return '#3fb950';
    return '#a371f7';
}

// ==================== Metrics ====================

async function loadMetrics() {
    try {
        const data = await api(`/api/runs/${state.currentRun}/metrics`);
        renderMetrics(data);
    } catch (error) {
        console.error('Failed to load metrics:', error);
    }
}

function renderMetrics(data) {
    // Destroy existing charts
    Object.values(state.charts).forEach(chart => chart.destroy());
    state.charts = {};

    // Model comparison chart
    if (data.model_comparison && data.model_comparison.length > 0) {
        const ctx1 = document.getElementById('model-chart').getContext('2d');
        state.charts.model = new Chart(ctx1, {
            type: 'bar',
            data: {
                labels: data.model_comparison.map(m => m.model?.split('/').pop() || 'Unknown'),
                datasets: [{
                    label: 'Avg Lifespan',
                    data: data.model_comparison.map(m => m.avg_lifespan || 0),
                    backgroundColor: '#58a6ff',
                }, {
                    label: 'Avg Success Rate',
                    data: data.model_comparison.map(m => (m.avg_success || 0) * 100),
                    backgroundColor: '#3fb950',
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { labels: { color: '#c9d1d9' } }
                },
                scales: {
                    x: { ticks: { color: '#8b949e' }, grid: { color: '#30363d' } },
                    y: { ticks: { color: '#8b949e' }, grid: { color: '#30363d' } }
                }
            }
        });
    }

    // Interaction types chart
    if (data.interaction_breakdown && data.interaction_breakdown.length > 0) {
        const ctx2 = document.getElementById('interaction-chart').getContext('2d');
        state.charts.interaction = new Chart(ctx2, {
            type: 'doughnut',
            data: {
                labels: data.interaction_breakdown.map(i => i.interaction_type),
                datasets: [{
                    data: data.interaction_breakdown.map(i => i.count),
                    backgroundColor: ['#58a6ff', '#3fb950', '#a371f7', '#d29922', '#f85149', '#8b949e'],
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#c9d1d9' }
                    }
                }
            }
        });
    }

    // Conversation stats
    const stats = data.conversation_stats || {};
    document.getElementById('conv-stats').innerHTML = `
        <div class="stat-item">
            <div class="stat-value">${stats.total_conversations || 0}</div>
            <div class="stat-label">Total Conversations</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${stats.bots_with_conversations || 0}</div>
            <div class="stat-label">Bots</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${stats.task_conversations || 0}</div>
            <div class="stat-label">Task Executions</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${stats.reflection_conversations || 0}</div>
            <div class="stat-label">Reflections</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">$${(stats.total_cost || 0).toFixed(4)}</div>
            <div class="stat-label">Total Cost</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">${(stats.avg_latency_ms || 0).toFixed(0)}ms</div>
            <div class="stat-label">Avg Latency</div>
        </div>
    `;

    // Model table
    const tbody = document.querySelector('#model-table tbody');
    tbody.innerHTML = data.model_comparison.map(m => `
        <tr>
            <td>${m.model || 'Unknown'}</td>
            <td>${m.bot_count || 0}</td>
            <td>${(m.avg_lifespan || 0).toFixed(1)}</td>
            <td>${((m.avg_success || 0) * 100).toFixed(1)}%</td>
            <td>${((m.offspring_survival || 0) * 100).toFixed(1)}%</td>
            <td>$${(m.total_cost || 0).toFixed(4)}</td>
        </tr>
    `).join('');
}

// ==================== Conversations ====================

function initConversationSearch() {
    document.getElementById('conv-search-btn').addEventListener('click', () => {
        state.convPage = 0;
        loadConversations();
    });

    document.getElementById('conv-search').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            state.convPage = 0;
            loadConversations();
        }
    });

    document.getElementById('conv-type-filter').addEventListener('change', () => {
        state.convPage = 0;
        loadConversations();
    });

    document.getElementById('conv-model-filter').addEventListener('change', () => {
        state.convPage = 0;
        loadConversations();
    });

    document.getElementById('conv-prev').addEventListener('click', () => {
        if (state.convPage > 0) {
            state.convPage--;
            loadConversations();
        }
    });

    document.getElementById('conv-next').addEventListener('click', () => {
        state.convPage++;
        loadConversations();
    });
}

async function loadConversations() {
    const container = document.getElementById('conversations-list');
    container.innerHTML = '<div class="loading">Loading conversations...</div>';

    const search = document.getElementById('conv-search').value;
    const type = document.getElementById('conv-type-filter').value;
    const model = document.getElementById('conv-model-filter').value;

    try {
        let data;
        if (search) {
            data = await api(`/api/conversations/search?q=${encodeURIComponent(search)}&run_id=${state.currentRun}&limit=${state.convLimit}`);
            state.conversations = data.results;
        } else {
            const params = new URLSearchParams({
                run_id: state.currentRun,
                limit: state.convLimit,
                offset: state.convPage * state.convLimit,
            });
            if (type) params.set('interaction_type', type);
            if (model) params.set('model', model);

            data = await api(`/api/conversations?${params}`);
            state.conversations = data.conversations;
        }

        renderConversations();
        updatePagination();
    } catch (error) {
        container.innerHTML = '<div class="empty-state"><h3>Failed to load conversations</h3></div>';
    }
}

function renderConversations() {
    const container = document.getElementById('conversations-list');

    if (state.conversations.length === 0) {
        container.innerHTML = '<div class="empty-state"><h3>No conversations found</h3></div>';
        return;
    }

    container.innerHTML = state.conversations.map(conv => {
        const typeClass = conv.interaction_type.includes('task') ? 'task' :
                         conv.interaction_type.includes('reflection') ? 'reflection' : '';
        const date = new Date(conv.timestamp * 1000).toLocaleString();

        return `
            <div class="conversation-item" data-id="${conv.id}">
                <div class="conv-header">
                    <span class="conv-bot">${conv.bot_name}</span>
                    <span class="conv-type ${typeClass}">${conv.interaction_type}</span>
                </div>
                <div class="conv-preview">${conv.task_type ? `[${conv.task_type}] ` : ''}Click to view details</div>
                <div class="conv-meta">
                    <span>Model: ${conv.model}</span>
                    <span>Tokens: ${conv.input_tokens + conv.output_tokens}</span>
                    <span>Cost: $${conv.cost_usd.toFixed(4)}</span>
                    <span>${date}</span>
                </div>
            </div>
        `;
    }).join('');

    // Add click handlers
    container.querySelectorAll('.conversation-item').forEach(item => {
        item.addEventListener('click', () => showConversation(item.dataset.id));
    });
}

function updatePagination() {
    document.getElementById('conv-page').textContent = `Page ${state.convPage + 1}`;
    document.getElementById('conv-prev').disabled = state.convPage === 0;
    document.getElementById('conv-next').disabled = state.conversations.length < state.convLimit;
}

async function showConversation(id) {
    try {
        const conv = await api(`/api/conversations/${id}`);

        document.getElementById('modal-title').textContent = `${conv.bot_name} - ${conv.interaction_type}`;
        document.getElementById('modal-meta').innerHTML = `
            <span>Model: ${conv.model}</span>
            <span>Tokens: ${conv.input_tokens} in / ${conv.output_tokens} out</span>
            <span>Cost: $${conv.cost_usd.toFixed(4)}</span>
            <span>Latency: ${conv.latency_ms.toFixed(0)}ms</span>
            ${conv.success !== null ? `<span>Success: ${conv.success ? 'Yes' : 'No'}</span>` : ''}
            ${conv.score !== null ? `<span>Score: ${(conv.score * 100).toFixed(1)}%</span>` : ''}
        `;
        document.getElementById('modal-system').textContent = conv.system_prompt || '(none)';
        document.getElementById('modal-user').textContent = conv.user_prompt;
        document.getElementById('modal-response').textContent = conv.assistant_response || '(no response)';

        elements.modal.classList.add('active');
    } catch (error) {
        console.error('Failed to load conversation:', error);
    }
}

// ==================== Reflections ====================

function initReflectionFilters() {
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.reflectionType = btn.dataset.type;
            loadReflections();
        });
    });
}

async function loadReflections() {
    const container = document.getElementById('reflections-list');
    container.innerHTML = '<div class="loading">Loading reflections...</div>';

    try {
        const params = new URLSearchParams({ run_id: state.currentRun, limit: 50 });
        if (state.reflectionType) params.set('reflection_type', state.reflectionType);

        const data = await api(`/api/reflections?${params}`);
        renderReflections(data.reflections);
    } catch (error) {
        container.innerHTML = '<div class="empty-state"><h3>No reflections found</h3></div>';
    }
}

function renderReflections(reflections) {
    const container = document.getElementById('reflections-list');

    if (reflections.length === 0) {
        container.innerHTML = '<div class="empty-state"><h3>No reflections found</h3><p>Bots haven\'t reflected yet in this run.</p></div>';
        return;
    }

    container.innerHTML = reflections.map(ref => {
        const date = new Date(ref.timestamp * 1000).toLocaleString();
        const type = ref.interaction_type.replace('reflection_', '');

        return `
            <div class="reflection-item">
                <div class="reflection-header">
                    <span class="reflection-bot">${ref.bot_name}</span>
                    <span class="reflection-type">${type} - ${ref.model} - ${date}</span>
                </div>
                <div class="reflection-prompt">${ref.user_prompt.substring(0, 300)}${ref.user_prompt.length > 300 ? '...' : ''}</div>
                <div class="reflection-response">${ref.assistant_response || '(no response)'}</div>
            </div>
        `;
    }).join('');
}

// ==================== Modal ====================

function initModal() {
    elements.modal.querySelector('.close-btn').addEventListener('click', () => {
        elements.modal.classList.remove('active');
    });

    elements.modal.addEventListener('click', (e) => {
        if (e.target === elements.modal) {
            elements.modal.classList.remove('active');
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && elements.modal.classList.contains('active')) {
            elements.modal.classList.remove('active');
        }
    });
}
