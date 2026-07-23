// Global Application State
let metersData = [];
let currentPage = 1;
const pageSize = 20;
let totalMetersCount = 0;
let activeMeterId = null;

// Debouncing state
let searchTimeout = null;

// Chart.js Instances
let energyChartInstance = null;
let voltageChartInstance = null;

// API Base Path
const API_BASE = '/api/v1';

// Initial Load
document.addEventListener('DOMContentLoaded', () => {
    // Apply saved theme on start
    const savedTheme = localStorage.getItem('theme') || 'dark';
    if (savedTheme === 'light') {
        document.body.classList.add('light-theme');
    }
    
    initApp();
    setupEventListeners();
});

// App Initialization
async function initApp() {
    // 1. Fetch grid statistics & meters list
    fetchMeters();
    
    // 2. Fetch hierarchy tree
    fetchHierarchy();
    
    // 3. Fetch list of transformers to calculate count (or we get it from dashboard endpoint)
    fetchTransformersCount();
}

// Event Listeners Setup
function setupEventListeners() {
    // Search inputs
    const searchInput = document.getElementById('search-input');
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentPage = 1;
            fetchMeters();
        }, 300);
    });

    // Filters
    document.getElementById('status-filter').addEventListener('change', () => {
        currentPage = 1;
        fetchMeters();
    });
    
    document.getElementById('make-filter').addEventListener('change', () => {
        currentPage = 1;
        fetchMeters();
    });

    // Pagination
    document.getElementById('btn-prev').addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            fetchMeters();
        }
    });

    document.getElementById('btn-next').addEventListener('click', () => {
        const totalPages = Math.ceil(totalMetersCount / pageSize);
        if (currentPage < totalPages) {
            currentPage++;
            fetchMeters();
        }
    });

    // Close Details Panel
    document.getElementById('btn-close-detail').addEventListener('click', () => {
        closeDetailsPane();
    });

    // Detail Tabs Toggle
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            const targetTab = btn.getAttribute('data-tab');
            const tabContents = document.querySelectorAll('.tab-content');
            tabContents.forEach(content => content.classList.add('hidden'));
            document.getElementById(targetTab).classList.remove('hidden');
        });
    });

    // Theme Toggle listener
    document.getElementById('theme-toggle').addEventListener('click', () => {
        document.body.classList.toggle('light-theme');
        const activeTheme = document.body.classList.contains('light-theme') ? 'light' : 'dark';
        localStorage.setItem('theme', activeTheme);
        updateChartColors();
    });
}

// Fetch Meters List from Wrapper API
async function fetchMeters() {
    const q = document.getElementById('search-input').value;
    const status = document.getElementById('status-filter').value;
    const make = document.getElementById('make-filter').value;
    
    let url = `${API_BASE}/meters?page=${currentPage}&limit=${pageSize}`;
    if (q) url += `&q=${encodeURIComponent(q)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;
    if (make) url += `&make=${encodeURIComponent(make)}`;
    
    const tableBody = document.getElementById('meters-table-body');
    tableBody.innerHTML = `<tr><td colspan="6" class="td-loading">Fetching meters...</td></tr>`;

    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error('API request failed');
        const result = await response.json();
        
        metersData = result.data;
        totalMetersCount = result.total;
        
        // Update Stats Counters (Total, Active, Decom - based on metadata)
        document.getElementById('stat-total-meters').innerText = totalMetersCount;
        
        // Update header sync timestamp
        if (result.cached_last_updated) {
            const date = new Date(result.cached_last_updated * 1000);
            document.getElementById('sync-time').innerText = date.toLocaleTimeString() + ' (5m TTL)';
        }

        renderMetersTable();
        updatePaginationUI();
        
        // Update specific status counters based on a broader query (simplified from cached totals)
        if (!q && !status && !make) {
            // Only update counts if no filters are active to represent true totals
            let active = 0;
            let decom = 0;
            metersData.forEach(m => {
                if (m.status === 'Active') active++;
                else if (m.status === 'Decommissioned') decom++;
            });
            // Approximate total counts using a quick stateless call or just fallback to known counts
            // Since our wrapper caching endpoint returns totals, let's fetch a quick count filter
            fetchTrueStatsCounts();
        }
    } catch (error) {
        console.error('Failed to fetch meters list:', error);
        tableBody.innerHTML = `<tr><td colspan="6" class="td-loading text-warning">Failed to load meters. Verify backend server is running.</td></tr>`;
    }
}

// Fetch true active/decommissioned stats counts from API
async function fetchTrueStatsCounts() {
    try {
        const [activeRes, decomRes] = await Promise.all([
            fetch(`${API_BASE}/meters?limit=1&status=Active`),
            fetch(`${API_BASE}/meters?limit=1&status=Decommissioned`)
        ]);
        const activeData = await activeRes.json();
        const decomData = await decomRes.json();
        document.getElementById('stat-active-meters').innerText = activeData.total;
        document.getElementById('stat-decom-meters').innerText = decomData.total;
    } catch (e) {
        console.error("Failed to retrieve counts:", e);
    }
}

// Fetch transformers list length to populate counter
async function fetchTransformersCount() {
    try {
        const response = await fetch(`${API_BASE}/transformers?limit=1`);
        if (response.ok) {
            const result = await response.json();
            document.getElementById('stat-transformers').innerText = result.total;
        }
    } catch (error) {
        console.error('Failed to fetch transformers count:', error);
    }
}

// Render Table Rows
function renderMetersTable() {
    const tableBody = document.getElementById('meters-table-body');
    
    if (metersData.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="6" class="td-loading">No matching meters found.</td></tr>`;
        return;
    }
    
    tableBody.innerHTML = '';
    metersData.forEach(meter => {
        const tr = document.createElement('tr');
        if (activeMeterId === meter.meter_id) {
            tr.classList.add('active-row');
        }
        
        tr.innerHTML = `
            <td class="font-medium" style="color: var(--primary); font-weight:600;">${meter.meter_id}</td>
            <td>${meter.serial_number || '—'}</td>
            <td>${meter.make || '—'}</td>
            <td>${meter.phase_type || '—'}</td>
            <td><span class="badge-status ${getBadgeClass(meter.status)}">${meter.status || 'Unknown'}</span></td>
            <td><span style="font-family: monospace;">${meter.dt_code || '—'}</span></td>
        `;
        
        tr.addEventListener('click', () => {
            selectMeter(meter.meter_id);
        });
        tableBody.appendChild(tr);
    });
}

function getBadgeClass(status) {
    if (!status) return '';
    const s = status.toLowerCase();
    if (s === 'active') return 'active';
    if (s === 'decommissioned') return 'decommissioned';
    if (s === 'suspended') return 'suspended';
    return '';
}

// Pagination Controls UI Update
function updatePaginationUI() {
    const totalPages = Math.max(1, Math.ceil(totalMetersCount / pageSize));
    document.getElementById('pagination-info').innerText = `Page ${currentPage} of ${totalPages}`;
    
    document.getElementById('btn-prev').disabled = (currentPage === 1);
    document.getElementById('btn-next').disabled = (currentPage >= totalPages);
}

// Sidebar hierarchy fetch
async function fetchHierarchy() {
    const container = document.getElementById('hierarchy-tree');
    try {
        const response = await fetch(`${API_BASE}/hierarchy`);
        if (!response.ok) throw new Error('Failed to get hierarchy');
        const tree = await response.json();
        
        container.innerHTML = '';
        const rootElement = createTreeNode(tree);
        container.appendChild(rootElement);
    } catch (error) {
        console.error('Failed to render hierarchy:', error);
        container.innerHTML = `<div class="loading-spinner text-warning">Failed to load hierarchy tree.</div>`;
    }
}

// Recursive function to build tree nodes
function createTreeNode(node) {
    const div = document.createElement('div');
    div.classList.add('tree-node');
    
    const isLeaf = !node.children || node.children.length === 0;
    if (isLeaf && node.type === 'meter') {
        div.classList.add('meter-leaf');
    }
    
    const header = document.createElement('div');
    header.classList.add('tree-header');
    
    // Icon (carets or leaves)
    const iconSpan = document.createElement('span');
    iconSpan.classList.add('tree-icon');
    iconSpan.innerHTML = isLeaf ? '📄' : '▶';
    header.appendChild(iconSpan);
    
    // Type badge
    if (node.type !== 'root') {
        const badge = document.createElement('span');
        badge.classList.add('node-type-badge', `badge-${node.type}`);
        badge.innerText = node.type === 'substation' ? 'SubStn' : node.type;
        header.appendChild(badge);
    }
    
    // Label text
    const labelSpan = document.createElement('span');
    labelSpan.innerText = node.name;
    header.appendChild(labelSpan);
    
    div.appendChild(header);
    
    if (!isLeaf) {
        const childrenContainer = document.createElement('div');
        childrenContainer.classList.add('tree-node-children');
        
        node.children.forEach(child => {
            childrenContainer.appendChild(createTreeNode(child));
        });
        
        div.appendChild(childrenContainer);
        
        // Expand/Collapse logic
        header.addEventListener('click', (e) => {
            e.stopPropagation();
            div.classList.toggle('expanded');
        });
    } else {
        // Leaf meter click selects it
        header.addEventListener('click', (e) => {
            e.stopPropagation();
            
            // Highlight node in tree
            document.querySelectorAll('.tree-node.meter-leaf').forEach(n => {
                n.classList.remove('active-node');
            });
            div.classList.add('active-node');
            
            selectMeter(node.code);
        });
    }
    
    return div;
}

// Meter Selection & Detail Display
async function selectMeter(meterId) {
    activeMeterId = meterId;
    
    // Render selection in list table rows
    renderMetersTable();
    
    const detailsPane = document.getElementById('details-pane');
    const noSelectionView = detailsPane.querySelector('.no-selection-view');
    const meterContent = document.getElementById('meter-detail-content');
    
    noSelectionView.classList.add('hidden');
    meterContent.classList.remove('hidden');
    
    // Show Loading details...
    document.getElementById('detail-title-id').innerText = `Loading Meter ${meterId}...`;
    
    try {
        // Fetch Details
        const res = await fetch(`${API_BASE}/meters/${meterId}`);
        if (!res.ok) throw new Error('Meter detail request failed');
        const meter = await res.json();
        
        // Update Title & Badge
        document.getElementById('detail-title-id').innerText = `Meter ${meter.meter_id}`;
        
        const statusBadge = document.getElementById('detail-badge-status');
        statusBadge.innerText = meter.status || 'UNKNOWN';
        statusBadge.className = `detail-badge badge-status ${getBadgeClass(meter.status)}`;
        
        // Populate Properties
        document.getElementById('detail-serial').innerText = meter.serial_number || '—';
        document.getElementById('detail-make').innerText = meter.make || '—';
        document.getElementById('detail-phase').innerText = meter.phase_type || '—';
        document.getElementById('detail-install-type').innerText = meter.installation_type || '—';
        document.getElementById('detail-build').innerText = meter.build_type || '—';
        document.getElementById('detail-dt-code').innerText = meter.dt_code || '—';
        
        // Location
        const lat = meter.location?.latitude;
        const lng = meter.location?.longitude;
        document.getElementById('detail-lat').innerText = lat !== null && lat !== undefined ? lat : '—';
        document.getElementById('detail-lng').innerText = lng !== null && lng !== undefined ? lng : '—';
        
        const mapLink = document.getElementById('google-map-link');
        if (lat && lng) {
            mapLink.href = `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;
            mapLink.style.display = 'inline-block';
        } else {
            mapLink.style.display = 'none';
        }
        
        // Grid path
        const pathList = document.getElementById('detail-path-list');
        pathList.innerHTML = '';
        
        const hierarchyKeys = ['zone', 'circle', 'division', 'subdivision', 'substation', 'feeder', 'dt'];
        if (meter.hierarchy) {
            hierarchyKeys.forEach(key => {
                const item = meter.hierarchy[key];
                if (item && item.name) {
                    const li = document.createElement('li');
                    li.classList.add('path-item');
                    li.innerHTML = `
                        <span class="path-type">${key === 'substation' ? 'SubStn' : key}</span>
                        <span class="path-name">${item.name} (${item.code})</span>
                    `;
                    pathList.appendChild(li);
                }
            });
        }

        // Trigger dynamic energy readings query
        loadConsumptionTab(meterId);
        
    } catch (e) {
        console.error('Failed to load meter details:', e);
        document.getElementById('detail-title-id').innerText = `Error Loading ${meterId}`;
    }
}

// Load Consumption / Energy Timeseries Data
async function loadConsumptionTab(meterId) {
    const tableBody = document.getElementById('readings-table-body');
    tableBody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding: 1.5rem; color: var(--text-muted);">Retrieving historical timeseries log...</td></tr>`;

    try {
        const res = await fetch(`${API_BASE}/meters/${meterId}/consumption`);
        if (!res.ok) throw new Error('Consumption request failed');
        const data = await res.json();
        
        const readings = data.readings || [];
        
        if (readings.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding: 1.5rem; color: var(--text-muted);">No readings logs available for this meter.</td></tr>`;
            destroyCharts();
            return;
        }

        // Populate Table
        tableBody.innerHTML = '';
        // Show last 10 readings in table chronologically reversed
        const recentReadings = [...readings].reverse().slice(0, 10);
        recentReadings.forEach(r => {
            const tr = document.createElement('tr');
            
            // Format ISO timestamp to readable date/time
            let displayTime = r.raw_timestamp;
            try {
                const d = new Date(r.timestamp);
                displayTime = d.toLocaleString();
            } catch(err){}

            tr.innerHTML = `
                <td style="font-weight: 500;">${displayTime}</td>
                <td style="color: var(--success);">${r.kwh !== null ? r.kwh.toFixed(2) : '—'}</td>
                <td style="color: var(--info);">${r.kvah !== null ? r.kvah.toFixed(2) : '—'}</td>
                <td style="font-family: monospace;">${r.voltage_r !== null ? r.voltage_r.toFixed(0) + ' V' : '—'}</td>
            `;
            tableBody.appendChild(tr);
        });

        // Generate Plots
        renderCharts(readings);
        
    } catch (error) {
        console.error('Failed to retrieve consumption history:', error);
        tableBody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding: 1.5rem; color: var(--text-warning);">Failed to query consumption endpoints.</td></tr>`;
    }
}

// Render dynamic charts (Energy kWh/kVAh & Voltage)
function renderCharts(readings) {
    destroyCharts();
    
    const isLight = document.body.classList.contains('light-theme');
    const gridColor = isLight ? 'rgba(0, 0, 0, 0.05)' : 'rgba(255, 255, 255, 0.03)';
    const labelColor = isLight ? '#475569' : '#94a3b8';
    
    // Select last 30 data points for legible charting
    const chartData = readings.slice(-30);
    const labels = chartData.map(r => {
        try {
            const d = new Date(r.timestamp);
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch(e) {
            return r.raw_timestamp;
        }
    });
    
    const kwhData = chartData.map(r => r.kwh);
    const kvahData = chartData.map(r => r.kvah);
    const voltData = chartData.map(r => r.voltage_r);
    
    // Chart 1: Energy Consumed
    const ctxEnergy = document.getElementById('consumption-chart').getContext('2d');
    energyChartInstance = new Chart(ctxEnergy, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Active Energy (kWh)',
                    data: kwhData,
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.05)',
                    tension: 0.3,
                    borderWidth: 2,
                    fill: true
                },
                {
                    label: 'Apparent Energy (kVAh)',
                    data: kvahData,
                    borderColor: '#8b5cf6',
                    backgroundColor: 'rgba(139, 92, 246, 0.05)',
                    tension: 0.3,
                    borderWidth: 2,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: labelColor, font: { size: 9 } } }
            },
            scales: {
                x: { grid: { color: gridColor }, ticks: { color: labelColor, font: { size: 8 } } },
                y: { grid: { color: gridColor }, ticks: { color: labelColor, font: { size: 8 } } }
            }
        }
    });
    
    // Chart 2: Voltage Reading
    const ctxVoltage = document.getElementById('voltage-chart').getContext('2d');
    voltageChartInstance = new Chart(ctxVoltage, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Voltage Line R (V)',
                    data: voltData,
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.05)',
                    tension: 0.1,
                    borderWidth: 1.5,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: labelColor, font: { size: 9 } } }
            },
            scales: {
                x: { grid: { color: gridColor }, ticks: { color: labelColor, font: { size: 8 } } },
                y: { grid: { color: gridColor }, ticks: { color: labelColor, font: { size: 8 } } }
            }
        }
    });
}

function destroyCharts() {
    if (energyChartInstance) {
        energyChartInstance.destroy();
        energyChartInstance = null;
    }
    if (voltageChartInstance) {
        voltageChartInstance.destroy();
        voltageChartInstance = null;
    }
}

// Close Details Panel UI
function closeDetailsPane() {
    activeMeterId = null;
    
    // Unhighlight tree selection
    document.querySelectorAll('.tree-node.meter-leaf').forEach(n => {
        n.classList.remove('active-node');
    });
    
    // Unhighlight rows
    renderMetersTable();
    
    const detailsPane = document.getElementById('details-pane');
    const noSelectionView = detailsPane.querySelector('.no-selection-view');
    const meterContent = document.getElementById('meter-detail-content');
    
    noSelectionView.classList.remove('hidden');
    meterContent.classList.add('hidden');
    
    destroyCharts();
}

function updateChartColors() {
    const isLight = document.body.classList.contains('light-theme');
    const gridColor = isLight ? 'rgba(0, 0, 0, 0.05)' : 'rgba(255, 255, 255, 0.03)';
    const labelColor = isLight ? '#475569' : '#94a3b8';
    
    [energyChartInstance, voltageChartInstance].forEach(chart => {
        if (chart) {
            chart.options.scales.x.grid.color = gridColor;
            chart.options.scales.x.ticks.color = labelColor;
            chart.options.scales.y.grid.color = gridColor;
            chart.options.scales.y.ticks.color = labelColor;
            chart.options.plugins.legend.labels.color = labelColor;
            chart.update();
        }
    });
}
