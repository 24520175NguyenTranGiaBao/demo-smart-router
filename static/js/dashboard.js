(() => {
    "use strict";

    const API_ENDPOINTS = {
        block: "/api/block",
        unblock: "/api/unblock",
    };

    const dom = {
        deviceList: null,
        targetNodeSelect: null
    };

    let trafficChart;
    const maxDataPoints = 30; 
    let labels = [];
    let rxData = []; 
    let txData = []; 

    const firebaseConfig = {
        databaseURL: "https://nhom12-router-default-rtdb.firebaseio.com/"
    };

    if (!firebase.apps.length) {
        firebase.initializeApp(firebaseConfig);
    }
    const db = firebase.database();

    document.addEventListener("DOMContentLoaded", initializeDashboard);

    /**
     * Initialize dashboard UI bindings and realtime updates.
     */
    function initializeDashboard() {
        dom.deviceList = document.getElementById("device-list");
        dom.targetNodeSelect = document.getElementById("targetNodeSelect");

        if (!dom.deviceList) return;

        dom.deviceList.addEventListener("click", onDeviceActionClick);

        const btnApplyCustomRule = document.getElementById("btnApplyCustomRule");
        if (btnApplyCustomRule) {
            btnApplyCustomRule.addEventListener("click", sendCustomRule);
        }

        if (dom.targetNodeSelect) {
            dom.targetNodeSelect.addEventListener("change", () => {
                labels.length = 0;
                rxData.length = 0;
                txData.length = 0;
                if (trafficChart) trafficChart.update();
            });
        }

        startFirebaseListener();

        initChart();
        setInterval(updateChart, 1000); 
    }

    /**
     * Subscribe to Firebase changes and refresh device views.
     */
    function startFirebaseListener() {
        setLoadingState();

        const devicesRef = db.ref('router_status/connected_devices');

        devicesRef.on('value', (snapshot) => {
            const data = snapshot.val();

            const devices = Array.isArray(data) ? data : (data ? Object.values(data) : []);

            renderDeviceRows(devices);
            updateTargetDropdown(devices);
        }, (error) => {
            console.error("Firebase read error: ", error);
            setMessageState("Cannot connect to Realtime Database!", true);
        });
    }

    /**
     * Handle block/unblock actions from the device table.
     */
    function onDeviceActionClick(event) {
        const button = event.target.closest("button[data-action][data-mac]");
        if (!button) return;

        if (button.disabled) return;

        const mac = button.getAttribute("data-mac");
        const action = button.getAttribute("data-action");

        if (!mac || !action) return;
        toggleBlock(button, mac, action);
    }

    /**
     * Render the loading state while waiting for realtime data.
     */
    function setLoadingState() {
        dom.deviceList.innerHTML = `
            <tr>
                <td colspan="6" class="text-center py-4">
                    <div class="spinner-border text-primary" role="status"></div>
                    <p class="mt-2 text-muted">Connecting to Firebase cloud...</p>
                </td>
            </tr>
        `;
    }

    /**
     * Render a table-wide status message.
     */
    function setMessageState(message, isError = false) {
        const messageClass = isError ? "text-danger" : "text-muted";
        dom.deviceList.innerHTML = `<tr><td colspan="6" class="text-center py-4 ${messageClass}">${escapeHtml(message)}</td></tr>`;
    }

    /**
     * Render all device rows.
     */
    function renderDeviceRows(devices) {
        if (!devices.length) {
            setMessageState("No devices found on the network.");
            return;
        }
        const rows = devices.map((device) => createDeviceRowMarkup(device)).join("");
        dom.deviceList.innerHTML = rows;
    }

    /**
     * Build one table row for a device.
     */
    function createDeviceRowMarkup(device) {
        const isBlocked = Number(device.IsBlocked) === 1;
        const displayName = escapeHtml(device.CustomName || device.OriginalName || "Unknown");
        const ipAddress = escapeHtml(device.IpAddress || "-");
        const macAddress = escapeHtml(device.MacAddress || "-");
        const lastSeen = escapeHtml(device.LastSeen || "-");

        const statusBadge = createStatusBadgeMarkup(isBlocked, Boolean(device.IsOnline));
        const actionButton = createActionButtonMarkup(isBlocked, device.MacAddress || "");

        return `
            <tr>
                <td class="fw-bold align-middle">${displayName}</td>
                <td class="align-middle">${ipAddress}</td>
                <td class="mac-font align-middle">${macAddress}</td>
                <td class="align-middle">${statusBadge}</td>
                <td class="align-middle text-muted">${lastSeen}</td>
                <td class="text-center align-middle">${actionButton}</td>
            </tr>
        `;
    }

    /**
     * Build status badge HTML for a device.
     */
    function createStatusBadgeMarkup(isBlocked, isOnline) {
        if (isBlocked) return '<span class="badge bg-danger"><i class="fas fa-lock me-1"></i>Blocked</span>';
        if (isOnline) return '<span class="badge bg-success"><i class="fas fa-globe me-1"></i>Online</span>';
        return '<span class="badge bg-secondary"><i class="fas fa-moon me-1"></i>Offline</span>';
    }

    /**
     * Build block/unblock action button HTML.
     */
    function createActionButtonMarkup(isBlocked, macAddress) {
        const action = isBlocked ? "unblock" : "block";
        const icon = isBlocked ? "fa-unlock" : "fa-ban";
        const text = isBlocked ? "Unblock" : "Block MAC";
        const buttonClass = isBlocked ? "btn-outline-success" : "btn-outline-danger";
        return `<button type="button" class="btn btn-sm ${buttonClass}" data-action="${action}" data-mac="${escapeHtml(macAddress)}"><i class="fas ${icon} me-1"></i>${text}</button>`;
    }

    /**
     * Refresh target-device dropdown with latest connected devices.
     */
    function updateTargetDropdown(devices) {
        if (!dom.targetNodeSelect) return;
        const currentSelection = dom.targetNodeSelect.value;
        let optionsHtml = '<option value="">-- Select a device to monitor --</option>';

        devices.forEach(dev => {
            if (dev.IpAddress) {
                const name = dev.CustomName || dev.OriginalName || "Unknown";
                optionsHtml += `<option value="${dev.IpAddress}">${name} (${dev.IpAddress})</option>`;
            }
        });

        dom.targetNodeSelect.innerHTML = optionsHtml;

        if (currentSelection && Array.from(dom.targetNodeSelect.options).some(opt => opt.value === currentSelection)) {
            dom.targetNodeSelect.value = currentSelection;
            return;
        }

        const firstValidOption = Array.from(dom.targetNodeSelect.options).find(opt => opt.value);
        if (firstValidOption) dom.targetNodeSelect.value = firstValidOption.value;
    }

    /**
     * Send block/unblock request to backend and update UI state.
     */
    async function toggleBlock(button, mac, action) {
        const endpoint = action === "block" ? API_ENDPOINTS.block : API_ENDPOINTS.unblock;
        const originalHtml = button.innerHTML;

        setActionButtonLoading(button, action);

        try {
            const response = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mac }),
            });
            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            const payload = await response.json();
            if (payload.status !== "success") throw new Error(payload.message || "Unable to update status");

            applyImmediateActionState(button, action === "block");
        } catch (error) {
            console.error("Firewall error:", error);
            button.innerHTML = originalHtml;
            alert(error.message || "Connection error to router!");
        } finally {
            clearActionButtonLoading(button);
        }
    }

    /**
     * Show loading spinner on an action button.
     */
    function setActionButtonLoading(button, action) {
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        const loadingLabel = action === "block" ? "Blocking..." : "Unblocking...";
        button.innerHTML = `<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>${loadingLabel}`;
    }

    /**
     * Restore action button interactivity after API call.
     */
    function clearActionButtonLoading(button) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
    }

    /**
     * Apply an optimistic UI state after block/unblock action.
     */
    function applyImmediateActionState(button, isBlockedNow) {
        const nextAction = isBlockedNow ? "unblock" : "block";
        const nextIcon = isBlockedNow ? "fa-unlock" : "fa-ban";
        const nextText = isBlockedNow ? "Unblock" : "Block MAC";
        const nextClass = isBlockedNow ? "btn-outline-success" : "btn-outline-danger";

        button.setAttribute("data-action", nextAction);
        button.classList.remove("btn-outline-success", "btn-outline-danger");
        button.classList.add(nextClass);
        button.innerHTML = `<i class="fas ${nextIcon} me-1"></i>${nextText}`;

        const row = button.closest("tr");
        if (!row) return;

        const statusCell = row.querySelector("td:nth-child(4)");
        if (!statusCell) return;

        if (isBlockedNow) {
            statusCell.innerHTML = createStatusBadgeMarkup(true, true);
            return;
        }

        statusCell.innerHTML = '<span class="badge bg-warning text-dark"><i class="fas fa-spinner fa-spin me-1"></i>Updating...</span>';
    }

    /**
     * Submit a custom iptables rule from the modal form.
     */
    async function sendCustomRule() {
        const payload = {
            action: document.getElementById("ruleAction").value,
            chain: "FORWARD",
            protocol: document.getElementById("ruleProtocol").value,
            target: document.getElementById("ruleTarget").value,
            src_ip: document.getElementById("ruleSrcIp").value.trim() || null,
            dst_ip: document.getElementById("ruleDstIp").value.trim() || null,
            sport: document.getElementById("ruleSport").value.trim() || null,
            dport: document.getElementById("ruleDport").value.trim() || null
        };

        try {
            const response = await fetch("/api/custom_rule", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const result = await response.json();
            if (result.status === "success") {
                alert(result.message);
                const closeBtn = document.querySelector('#customRuleModal [data-bs-dismiss="modal"]');
                if (closeBtn) closeBtn.click();

                document.getElementById("customRuleForm").reset();
            } else {
                alert("Error: " + result.message);
            }
        } catch (error) {
            alert("Connection error to router!");
        }
    }

    /**
     * Initialize the realtime traffic chart.
     */
    function initChart() {
        const ctx = document.getElementById('trafficChart').getContext('2d');
        trafficChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    { label: 'Upload (RX KB/s)', data: rxData, borderColor: '#e74c3c', backgroundColor: 'rgba(231, 76, 60, 0.2)', fill: true, tension: 0.4 },
                    { label: 'Download (TX KB/s)', data: txData, borderColor: '#2ecc71', backgroundColor: 'rgba(46, 204, 113, 0.2)', fill: true, tension: 0.4 }
                ]
            },
            options: { responsive: true, animation: false, scales: { y: { beginAtZero: true } } }
        });
    }

    /**
     * Poll backend stats endpoint and append points to chart.
     */
    async function updateChart() {
        if (!dom.targetNodeSelect) return;
        const selectedIp = dom.targetNodeSelect.value;
        if (!selectedIp) return;

        try {
            const res = await fetch(`/api/stats?ip=${encodeURIComponent(selectedIp)}`);
            const json = await res.json();
            
            if (json.status === 'success') {
                if (labels.length >= maxDataPoints) { 
                    labels.shift(); rxData.shift(); txData.shift(); 
                }
                labels.push(json.timestamp);
                rxData.push(json.client_upload_kbps);
                txData.push(json.client_download_kbps);
                trafficChart.update();
            }
        } catch (error) {
            console.error("Chart error:", error);
        }
    }

    /**
     * Escape HTML-sensitive characters for safe rendering.
     */
    function escapeHtml(value) {
        return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;").replace(/'/g, "&#39;");
    }
})();