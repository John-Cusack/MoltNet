// MoltNet Observatory Dashboard JavaScript

// Configuration
let config = {
    pollIntervalMs: 5000,
};

// Charts
let fitnessChart = null;
let walletChart = null;

// State
let isConnected = false;
let lastUpdate = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
    await loadConfig();
    initCharts();
    await refreshAll();
    startPolling();
});

// Load configuration from server
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        if (response.ok) {
            config = await response.json();
            document.getElementById('poll-interval').textContent =
                Math.round(config.poll_interval_ms / 1000);
        }
    } catch (error) {
        console.error('Failed to load config:', error);
    }
}

// Initialize Chart.js charts
function initCharts() {
    const chartOptions = {
        responsive: true,
        maintainAspectRatio: true,
        animation: { duration: 300 },
        plugins: {
            legend: { display: false },
        },
        scales: {
            x: {
                type: 'category',
                grid: { color: 'rgba(48, 54, 61, 0.5)' },
                ticks: { color: '#8b949e', maxRotation: 0 },
            },
            y: {
                grid: { color: 'rgba(48, 54, 61, 0.5)' },
                ticks: { color: '#8b949e' },
            },
        },
    };

    // Fitness chart
    const fitnessCtx = document.getElementById('fitness-chart').getContext('2d');
    fitnessChart = new Chart(fitnessCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Avg Fitness',
                data: [],
                borderColor: '#58a6ff',
                backgroundColor: 'rgba(88, 166, 255, 0.1)',
                fill: true,
                tension: 0.4,
            }],
        },
        options: {
            ...chartOptions,
            scales: {
                ...chartOptions.scales,
                y: {
                    ...chartOptions.scales.y,
                    min: 0,
                    max: 1,
                },
            },
        },
    });

    // Wallet chart
    const walletCtx = document.getElementById('wallet-chart').getContext('2d');
    walletChart = new Chart(walletCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Wallet Balance',
                data: [],
                borderColor: '#3fb950',
                backgroundColor: 'rgba(63, 185, 80, 0.1)',
                fill: true,
                tension: 0.4,
            }],
        },
        options: chartOptions,
    });
}

// Start polling for updates
function startPolling() {
    setInterval(refreshAll, config.poll_interval_ms || 5000);
}

// Refresh all data
async function refreshAll() {
    try {
        await Promise.all([
            refreshStats(),
            refreshCharts(),
            refreshLeaderboard(),
            refreshBotList(),
            refreshEvents(),
        ]);

        setConnectionStatus(true);
        updateLastUpdate();
    } catch (error) {
        console.error('Refresh failed:', error);
        setConnectionStatus(false);
    }
}

// Set connection status indicator
function setConnectionStatus(connected) {
    const indicator = document.getElementById('connection-status');
    isConnected = connected;

    if (connected) {
        indicator.textContent = 'Connected';
        indicator.className = 'status-indicator connected';
    } else {
        indicator.textContent = 'Connection Error';
        indicator.className = 'status-indicator error';
    }
}

// Update last update timestamp
function updateLastUpdate() {
    lastUpdate = new Date();
    document.getElementById('last-update').textContent =
        `Last update: ${lastUpdate.toLocaleTimeString()}`;
}

// Refresh colony stats
async function refreshStats() {
    const response = await fetch('/api/colony/stats');
    if (!response.ok) throw new Error('Failed to fetch stats');

    const stats = await response.json();

    document.getElementById('stat-active-bots').textContent = stats.active_bots;
    document.getElementById('stat-total-bots').textContent = stats.total_bots;
    document.getElementById('stat-avg-fitness').textContent =
        stats.avg_fitness.toFixed(3);
    document.getElementById('stat-revenue').textContent =
        '$' + stats.total_revenue.toFixed(4);
    document.getElementById('stat-api-spend').textContent =
        '$' + stats.total_api_spend.toFixed(4);
}

// Refresh charts
async function refreshCharts() {
    // Fetch fitness time series
    const fitnessResponse = await fetch('/api/timeseries/fitness_score?since_seconds=3600&bucket_seconds=60');
    if (fitnessResponse.ok) {
        const data = await fitnessResponse.json();
        updateChart(fitnessChart, data.points);
    }

    // Fetch wallet time series
    const walletResponse = await fetch('/api/timeseries/wallet_balance?since_seconds=3600&bucket_seconds=60');
    if (walletResponse.ok) {
        const data = await walletResponse.json();
        updateChart(walletChart, data.points);
    }
}

// Update a chart with new data
function updateChart(chart, points) {
    const labels = points.map(p => {
        const date = new Date(p.timestamp);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });

    const values = points.map(p => p.value);

    chart.data.labels = labels;
    chart.data.datasets[0].data = values;
    chart.update('none');
}

// Refresh brain leaderboard
async function refreshLeaderboard() {
    const response = await fetch('/api/brains/leaderboard');
    if (!response.ok) throw new Error('Failed to fetch leaderboard');

    const data = await response.json();
    const tbody = document.querySelector('#brain-leaderboard tbody');

    if (data.leaderboard.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No data yet</td></tr>';
        return;
    }

    tbody.innerHTML = data.leaderboard.map(entry => `
        <tr>
            <td>${formatModelName(entry.brain_model)}</td>
            <td>${entry.usage_count}</td>
            <td>${entry.avg_fitness.toFixed(3)}</td>
            <td>$${entry.total_revenue.toFixed(4)}</td>
        </tr>
    `).join('');
}

// Refresh bot list
async function refreshBotList() {
    const response = await fetch('/api/colony/current');
    if (!response.ok) throw new Error('Failed to fetch bots');

    const data = await response.json();
    const tbody = document.querySelector('#bot-list tbody');

    if (data.bots.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No active bots</td></tr>';
        return;
    }

    tbody.innerHTML = data.bots.map(bot => `
        <tr>
            <td>${bot.bot_name}</td>
            <td>${bot.generation ?? '-'}</td>
            <td>${bot.fitness_score?.toFixed(3) ?? '-'}</td>
            <td>${formatState(bot.state)}</td>
            <td>${formatModelName(bot.brain_primary)}</td>
        </tr>
    `).join('');
}

// Refresh events
async function refreshEvents() {
    const response = await fetch('/api/events/recent?limit=20');
    if (!response.ok) throw new Error('Failed to fetch events');

    const data = await response.json();
    const container = document.getElementById('events-list');

    if (data.events.length === 0) {
        container.innerHTML = '<div class="empty-state">No events yet</div>';
        return;
    }

    container.innerHTML = data.events.map(event => `
        <div class="event-item">
            <span class="event-type ${getEventTypeClass(event.event_type)}">
                ${event.event_type}
            </span>
            <span class="event-content">
                ${event.bot_name ? `<span class="event-bot">${event.bot_name}</span>: ` : ''}
                ${formatEventData(event.data)}
            </span>
            <span class="event-time">${formatTime(event.timestamp)}</span>
        </div>
    `).join('');
}

// Format model name for display
function formatModelName(name) {
    if (!name) return '-';
    // Remove provider prefix if present
    const parts = name.split('/');
    return parts[parts.length - 1];
}

// Format state as a badge
function formatState(state) {
    if (!state) return '<span class="state-badge state-idle">unknown</span>';

    const stateClass = {
        'active': 'state-active',
        'running': 'state-active',
        'idle': 'state-idle',
        'waiting': 'state-idle',
        'replicating': 'state-replicating',
        'error': 'state-error',
        'failed': 'state-error',
    }[state.toLowerCase()] || 'state-idle';

    return `<span class="state-badge ${stateClass}">${state}</span>`;
}

// Get event type CSS class
function getEventTypeClass(eventType) {
    if (eventType.includes('replicat')) return 'replication';
    if (eventType.includes('error') || eventType.includes('fail')) return 'error';
    if (eventType.includes('task') || eventType.includes('complete')) return 'task';
    return '';
}

// Format event data for display
function formatEventData(data) {
    if (!data) return '';
    if (typeof data === 'string') return data;

    // Try to extract a meaningful message
    if (data.message) return data.message;
    if (data.error) return data.error;
    if (data.task) return `Task: ${data.task}`;

    // Fallback to JSON
    return JSON.stringify(data);
}

// Format timestamp for display
function formatTime(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;

    if (diffMs < 60000) {
        return 'just now';
    } else if (diffMs < 3600000) {
        const mins = Math.floor(diffMs / 60000);
        return `${mins}m ago`;
    } else if (diffMs < 86400000) {
        const hours = Math.floor(diffMs / 3600000);
        return `${hours}h ago`;
    } else {
        return date.toLocaleDateString();
    }
}
