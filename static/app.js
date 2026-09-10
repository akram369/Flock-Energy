// Global Application State
let metersData = [];
let currentPage = 1;
const pageSize = 20;
let totalMetersCount = 0;
let activeMeterId = null;
let activeHierarchyFilter = null;

// Debouncing state
let searchTimeout = null;

// Chart.js Instances
let energyChartInstance = null;
let voltageChartInstance = null;
let makesChartInstance = null;
let phasesChartInstance = null;

// Leaflet Map State
let leafletMap = null;
let mapMarkersLayer = null;
let searchRadiusCircle = null;
let allMetersGeoData = [];

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
    
    // 3. Fetch transformers count
    fetchTransformersCount();
    
    // 4. Fetch all meters for geo map in background
    fetchAllMetersForMap();
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

    // Detail Tabs Toggle (Nameplate vs Consumption)
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            const targetTab = btn.getAttribute('data-tab');
            const tabContents = document.querySelectorAll('.tab-content');
            tabContents.forEach(content => content.classList.add('hidden'));
            document.getElementById(targetTab).classList.remove('hidden');
        });
    });

    // Main View Switcher Tabs (Inventory / Map / Analytics)
    const viewTabBtns = document.querySelectorAll('.view-tab-btn');
    viewTabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            viewTabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            const targetView = btn.getAttribute('data-view');
            document.querySelectorAll('.view-section').forEach(sec => sec.classList.add('hidden'));
            const activeSection = document.getElementById(targetView);
            activeSection.classList.remove('hidden');
            
            if (targetView === 'view-map') {
                setTimeout(() => {
                    initOrInvalidateMap();
                }, 100);
            } else if (targetView === 'view-analytics') {
                loadAnalyticsDashboard();
            }
        });
    });

    // Locate on map button from details view
    document.getElementById('btn-locate-on-map').addEventListener('click', () => {
        if (activeMeterId) {
            document.getElementById('btn-view-map').click();
            locateMeterOnMap(activeMeterId);
        }
    });

    // Clear radius search button
    document.getElementById('btn-clear-map-search').addEventListener('click', () => {
        if (searchRadiusCircle && leafletMap) {
            leafletMap.removeLayer(searchRadiusCircle);
            searchRadiusCircle = null;
        }
        renderMapMarkers(allMetersGeoData);
    });

    // Manual Cache Refresh Sync button
    document.getElementById('btn-manual-sync').addEventListener('click', async () => {
        const syncBtn = document.getElementById('btn-manual-sync');
        syncBtn.innerText = '⏳ Syncing...';
        syncBtn.disabled = true;
        try {
            const res = await fetch(`${API_BASE}/cache/refresh`, { method: 'POST' });
            if (res.ok) {
                syncBtn.innerText = '✅ Synced!';
                fetchMeters();
                fetchHierarchy();
                fetchAllMetersForMap();
            }
        } catch (e) {
            syncBtn.innerText = '❌ Failed';
        }
        setTimeout(() => {
            syncBtn.innerText = '🔄 Sync';
            syncBtn.disabled = false;
        }, 2500);
    });

    // Active hierarchy filter clear
    document.getElementById('active-filter-badge').addEventListener('click', () => {
        activeHierarchyFilter = null;
        document.getElementById('active-filter-badge').classList.add('hidden');
        document.querySelectorAll('.tree-node.meter-leaf, .tree-header').forEach(n => n.classList.remove('active-node'));
        currentPage = 1;
        fetchMeters();
    });

    // Theme Toggle listener
    document.getElementById('theme-toggle').addEventListener('click', () => {
        document.body.classList.toggle('light-theme');
        const activeTheme = document.body.classList.contains('light-theme') ? 'light' : 'dark';
        localStorage.setItem('theme', activeTheme);
        updateChartColors();
        if (leafletMap) {
            updateMapTiles(activeTheme);
        }
    });
}

// Fetch Meters List from API Wrapper
async function fetchMeters() {
    const q = document.getElementById('search-input').value;
    const status = document.getElementById('status-filter').value;
    const make = document.getElementById('make-filter').value;
    
    let url = `${API_BASE}/meters?page=${currentPage}&limit=${pageSize}`;
    if (q) url += `&q=${encodeURIComponent(q)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;
    if (make) url += `&make=${encodeURIComponent(make)}`;
    if (activeHierarchyFilter) url += `&dt_code=${encodeURIComponent(activeHierarchyFilter)}`;
    
    const tableBody = document.getElementById('meters-table-body');
    tableBody.innerHTML = `<tr><td colspan="6" class="td-loading">Fetching meters...</td></tr>`;

    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error('API request failed');
        const result = await response.json();
        
        metersData = result.data;
        totalMetersCount = result.total;
        
        document.getElementById('stat-total-meters').innerText = totalMetersCount;
        
        if (result.cached_last_updated) {
            const date = new Date(result.cached_last_updated * 1000);
            document.getElementById('sync-time').innerText = date.toLocaleTimeString() + ' (5m TTL)';
        }

        renderMetersTable();
        updatePaginationUI();
        
        if (!q && !status && !make && !activeHierarchyFilter) {
            fetchTrueStatsCounts();
        }
    } catch (error) {
        console.error('Failed to fetch meters list:', error);
        tableBody.innerHTML = `<tr><td colspan="6" class="td-loading text-warning">Failed to load meters. Verify backend server is running.</td></tr>`;
    }
}

// Fetch true stats counts from API
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

// Fetch transformers count
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

// Fetch all meters data for map plotting
async function fetchAllMetersForMap() {
    try {
        const response = await fetch(`${API_BASE}/meters?limit=100&page=1`);
        if (!response.ok) return;
        const firstPage = await response.json();
        const total = firstPage.total;
        
        // Fetch remaining in parallel batches if needed, or query with a high limit
        const allRes = await fetch(`${API_BASE}/meters?limit=${total}`);
        if (allRes.ok) {
            const allData = await allRes.json();
            allMetersGeoData = allData.data;
            if (leafletMap) {
                renderMapMarkers(allMetersGeoData);
            }
        }
    } catch (e) {
        console.error("Failed to fetch all meters for map:", e);
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
            <td>${meter.phase_type ? meter.phase_type.toUpperCase() : '—'}</td>
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
    
    const iconSpan = document.createElement('span');
    iconSpan.classList.add('tree-icon');
    iconSpan.innerHTML = isLeaf ? '📄' : '▶';
    header.appendChild(iconSpan);
    
    if (node.type !== 'root') {
        const badge = document.createElement('span');
        badge.classList.add('node-type-badge', `badge-${node.type}`);
        badge.innerText = node.type === 'substation' ? 'SubStn' : node.type;
        header.appendChild(badge);
    }
    
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
        
        header.addEventListener('click', (e) => {
            e.stopPropagation();
            div.classList.toggle('expanded');
            
            // If user clicks a DT node, filter the inventory table by that DT
            if (node.type === 'dt') {
                filterByDT(node.code, node.name);
            }
        });
    } else {
        header.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.tree-node.meter-leaf').forEach(n => n.classList.remove('active-node'));
            div.classList.add('active-node');
            selectMeter(node.code);
            // Switch to inventory view if not already there
            document.querySelector('[data-view="view-inventory"]').click();
        });
    }
    
    return div;
}

// Filter table by DT from hierarchy click
function filterByDT(dtCode, dtName) {
    activeHierarchyFilter = dtCode;
    const filterBadge = document.getElementById('active-filter-badge');
    filterBadge.innerText = `DT: ${dtCode} ✕`;
    filterBadge.classList.remove('hidden');
    
    // Switch to inventory view
    document.querySelector('[data-view="view-inventory"]').click();
    currentPage = 1;
    fetchMeters();
}

// Meter Selection & Detail Display
async function selectMeter(meterId) {
    activeMeterId = meterId;
    renderMetersTable();
    
    const detailsPane = document.getElementById('details-pane');
    const noSelectionView = detailsPane.querySelector('.no-selection-view');
    const meterContent = document.getElementById('meter-detail-content');
    
    noSelectionView.classList.add('hidden');
    meterContent.classList.remove('hidden');
    
    document.getElementById('detail-title-id').innerText = `Loading Meter ${meterId}...`;
    
    try {
        const res = await fetch(`${API_BASE}/meters/${meterId}`);
        if (!res.ok) throw new Error('Meter detail request failed');
        const meter = await res.json();
        
        document.getElementById('detail-title-id').innerText = `Meter ${meter.meter_id}`;
        
        const statusBadge = document.getElementById('detail-badge-status');
        statusBadge.innerText = meter.status || 'UNKNOWN';
        statusBadge.className = `detail-badge badge-status ${getBadgeClass(meter.status)}`;
        
        document.getElementById('detail-serial').innerText = meter.serial_number || '—';
        document.getElementById('detail-make').innerText = meter.make || '—';
        document.getElementById('detail-phase').innerText = meter.phase_type ? meter.phase_type.toUpperCase() : '—';
        document.getElementById('detail-install-type').innerText = meter.installation_type || '—';
        document.getElementById('detail-build').innerText = meter.build_type || '—';
        document.getElementById('detail-dt-code').innerText = meter.dt_code || '—';
        
        const lat = meter.location?.latitude;
        const lng = meter.location?.longitude;
        document.getElementById('detail-lat').innerText = lat !== null && lat !== undefined ? lat : '—';
        document.getElementById('detail-lng').innerText = lng !== null && lng !== undefined ? lng : '—';
        
        const mapLink = document.getElementById('google-map-link');
        const locateMapBtn = document.getElementById('btn-locate-on-map');
        if (lat && lng) {
            mapLink.href = `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;
            mapLink.style.display = 'inline-block';
            locateMapBtn.style.display = 'inline-block';
        } else {
            mapLink.style.display = 'none';
            locateMapBtn.style.display = 'none';
        }
        
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

        tableBody.innerHTML = '';
        const recentReadings = [...readings].reverse().slice(0, 10);
        recentReadings.forEach(r => {
            const tr = document.createElement('tr');
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

        renderCharts(readings);
    } catch (error) {
        console.error('Failed to retrieve consumption history:', error);
        tableBody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding: 1.5rem; color: var(--text-warning);">Failed to query consumption endpoint.</td></tr>`;
    }
}

// Render dynamic charts (Energy kWh/kVAh & Voltage)
function renderCharts(readings) {
    destroyCharts();
    
    const isLight = document.body.classList.contains('light-theme');
    const gridColor = isLight ? 'rgba(0, 0, 0, 0.05)' : 'rgba(255, 255, 255, 0.03)';
    const labelColor = isLight ? '#475569' : '#94a3b8';
    
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
                    backgroundColor: 'rgba(16, 185, 129, 0.08)',
                    tension: 0.3,
                    borderWidth: 2,
                    fill: true
                },
                {
                    label: 'Apparent Energy (kVAh)',
                    data: kvahData,
                    borderColor: '#8b5cf6',
                    backgroundColor: 'rgba(139, 92, 246, 0.08)',
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
    document.querySelectorAll('.tree-node.meter-leaf').forEach(n => n.classList.remove('active-node'));
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

// --- LEAFLET MAP MODULE ---

let mapTileLayer = null;

function initOrInvalidateMap() {
    const mapEl = document.getElementById('meters-map');
    if (!leafletMap) {
        // Center around Jaipur Rajasthan coordinates
        leafletMap = L.map('meters-map').setView([26.9124, 75.8200], 12);
        
        const isLight = document.body.classList.contains('light-theme');
        const tileUrl = isLight 
            ? 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
            : 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
            
        mapTileLayer = L.tileLayer(tileUrl, {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 19
        }).addTo(leafletMap);
        
        mapMarkersLayer = L.layerGroup().addTo(leafletMap);
        
        // Click on map to trigger radius search
        leafletMap.on('click', (e) => {
            const radiusKm = parseFloat(document.getElementById('map-radius-input').value) || 5.0;
            performMapRadiusSearch(e.latlng.lat, e.latlng.lng, radiusKm);
        });
        
        if (allMetersGeoData.length > 0) {
            renderMapMarkers(allMetersGeoData);
        } else {
            fetchAllMetersForMap();
        }
    } else {
        leafletMap.invalidateSize();
    }
}

function updateMapTiles(theme) {
    if (!leafletMap || !mapTileLayer) return;
    const tileUrl = theme === 'light'
        ? 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
        : 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
    leafletMap.removeLayer(mapTileLayer);
    mapTileLayer = L.tileLayer(tileUrl, {
        attribution: '&copy; OpenStreetMap, &copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(leafletMap);
}

function renderMapMarkers(meters) {
    if (!mapMarkersLayer) return;
    mapMarkersLayer.clearLayers();
    
    meters.forEach(m => {
        if (!m.location || m.location.latitude === null || m.location.longitude === null) return;
        
        const lat = m.location.latitude;
        const lng = m.location.longitude;
        
        let color = '#10b981'; // Active green
        if (m.status === 'Decommissioned') color = '#f59e0b'; // Amber
        else if (m.status === 'Suspended') color = '#ef4444'; // Red
        
        const circle = L.circleMarker([lat, lng], {
            radius: 5,
            fillColor: color,
            color: '#ffffff',
            weight: 1,
            opacity: 0.8,
            fillOpacity: 0.75
        });
        
        const popupContent = `
            <div class="map-popup-card">
                <div class="map-popup-header">
                    <span class="map-popup-title">${m.meter_id}</span>
                    <span class="badge-status ${getBadgeClass(m.status)}">${m.status || 'Active'}</span>
                </div>
                <div class="map-popup-detail">
                    <div><strong>Make:</strong> ${m.make || '—'} (${m.phase_type ? m.phase_type.toUpperCase() : '1-PH'})</div>
                    <div><strong>DT Code:</strong> ${m.dt_code || '—'}</div>
                    <div><strong>Coordinates:</strong> ${lat.toFixed(4)}, ${lng.toFixed(4)}</div>
                </div>
                <button class="btn-popup-select" onclick="handleMapSelectMeter('${m.meter_id}')">View Telemetry & Details</button>
            </div>
        `;
        
        circle.bindPopup(popupContent);
        mapMarkersLayer.addLayer(circle);
    });
}

// Global handler invoked from popup click
window.handleMapSelectMeter = function(meterId) {
    document.querySelector('[data-view="view-inventory"]').click();
    selectMeter(meterId);
};

// Map Radius Search handler
async function performMapRadiusSearch(lat, lng, radiusKm) {
    if (searchRadiusCircle && leafletMap) {
        leafletMap.removeLayer(searchRadiusCircle);
    }
    
    searchRadiusCircle = L.circle([lat, lng], {
        radius: radiusKm * 1000,
        color: '#0284c7',
        fillColor: '#0284c7',
        fillOpacity: 0.15,
        weight: 2
    }).addTo(leafletMap);
    
    try {
        const res = await fetch(`${API_BASE}/meters/nearby?lat=${lat}&lng=${lng}&radius_km=${radiusKm}&limit=200`);
        if (res.ok) {
            const data = await res.json();
            renderMapMarkers(data.data);
            
            L.popup()
                .setLatLng([lat, lng])
                .setContent(`
                    <div style="padding: 0.25rem; font-size: 0.8rem;">
                        <strong>Radius Search Center</strong><br>
                        Found <strong>${data.total}</strong> meters within ${radiusKm} km.
                    </div>
                `)
                .openOn(leafletMap);
        }
    } catch (e) {
        console.error("Radius search failed:", e);
    }
}

// Locate specific meter on map
function locateMeterOnMap(meterId) {
    const meter = allMetersGeoData.find(m => m.meter_id === meterId);
    if (meter && meter.location && meter.location.latitude && meter.location.longitude && leafletMap) {
        const lat = meter.location.latitude;
        const lng = meter.location.longitude;
        leafletMap.setView([lat, lng], 15);
    }
}

// --- ANALYTICS DASHBOARD MODULE ---

async function loadAnalyticsDashboard() {
    try {
        const res = await fetch(`${API_BASE}/analytics/summary`);
        if (!res.ok) throw new Error("Analytics request failed");
        const data = await res.json();
        
        // Render Make Share Doughnut Chart
        renderMakesChart(data.make_breakdown);
        
        // Render Phase Bar Chart
        renderPhasesChart(data.phase_breakdown);
        
        // Render Top DTs Table
        renderTopDTsTable(data.top_transformers_by_meters);
        
        // Render Anomalies Counters
        document.getElementById('anomaly-inactive-count').innerText = data.anomalies.inactive_meter_count;
        document.getElementById('anomaly-missing-geo').innerText = data.anomalies.missing_geo_count;
        document.getElementById('anomaly-unlinked-dt').innerText = data.anomalies.unlinked_dt_count;
    } catch (e) {
        console.error("Failed to load analytics dashboard:", e);
    }
}

function renderMakesChart(makeData) {
    if (makesChartInstance) {
        makesChartInstance.destroy();
    }
    
    const isLight = document.body.classList.contains('light-theme');
    const labelColor = isLight ? '#475569' : '#cbd5e1';
    
    const labels = makeData.map(m => `${m.make} (${m.percentage}%)`);
    const counts = makeData.map(m => m.count);
    
    const ctx = document.getElementById('chart-makes-distribution').getContext('2d');
    makesChartInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: counts,
                backgroundColor: ['#0284c7', '#10b981', '#f59e0b', '#8b5cf6', '#64748b'],
                borderColor: isLight ? '#ffffff' : '#0f1420',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: { color: labelColor, font: { size: 10 } }
                }
            }
        }
    });
}

function renderPhasesChart(phaseData) {
    if (phasesChartInstance) {
        phasesChartInstance.destroy();
    }
    
    const isLight = document.body.classList.contains('light-theme');
    const labelColor = isLight ? '#475569' : '#cbd5e1';
    const gridColor = isLight ? 'rgba(0, 0, 0, 0.05)' : 'rgba(255, 255, 255, 0.03)';
    
    const labels = phaseData.map(p => p.phase);
    const counts = phaseData.map(p => p.count);
    
    const ctx = document.getElementById('chart-phases-distribution').getContext('2d');
    phasesChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Installed Meters',
                data: counts,
                backgroundColor: ['#10b981', '#0284c7'],
                borderRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: { grid: { display: false }, ticks: { color: labelColor, font: { size: 10 } } },
                y: { grid: { color: gridColor }, ticks: { color: labelColor, font: { size: 10 } } }
            }
        }
    });
}

function renderTopDTsTable(dts) {
    const tbody = document.getElementById('analytics-dts-body');
    tbody.innerHTML = '';
    
    dts.forEach(dt => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td style="font-family: monospace; font-weight: 600; color: var(--primary);">${dt.dt_code}</td>
            <td>${dt.dt_name}</td>
            <td style="font-weight: 600;">${dt.meter_count} meters</td>
            <td style="color: var(--text-muted);">${dt.capacity_kva ? dt.capacity_kva + ' kVA' : '—'}</td>
        `;
        tbody.appendChild(tr);
    });
}
