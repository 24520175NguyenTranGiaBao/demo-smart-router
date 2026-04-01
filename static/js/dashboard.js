(() => {
    "use strict";

    const API_ENDPOINTS = {
        devices: "/api/devices",
        block: "/api/block",
        unblock: "/api/unblock",
    };

    const dom = {
        deviceList: null,
        refreshButton: null,
    };

    document.addEventListener("DOMContentLoaded", initializeDashboard);

    function initializeDashboard() {
        dom.deviceList = document.getElementById("device-list");
        dom.refreshButton = document.getElementById("refresh-devices-btn");

        if (!dom.deviceList) {
            console.error("Missing #device-list element");
            return;
        }

        if (dom.refreshButton) {
            dom.refreshButton.addEventListener("click", loadDevices);
        }

        dom.deviceList.addEventListener("click", onDeviceActionClick);

        loadDevices();
    }

    function onDeviceActionClick(event) {
        const button = event.target.closest("button[data-action][data-mac]");

        if (!button) {
            return;
        }

        const mac = button.getAttribute("data-mac");
        const action = button.getAttribute("data-action");

        if (!mac || !action) {
            return;
        }

        toggleBlock(mac, action);
    }

    function setLoadingState() {
        dom.deviceList.innerHTML = `
            <tr>
                <td colspan="6" class="text-center py-4">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <p class="mt-2 text-muted">Refreshing data...</p>
                </td>
            </tr>
        `;
    }

    function setMessageState(message, isError = false) {
        const messageClass = isError ? "text-danger" : "text-muted";

        dom.deviceList.innerHTML = `
            <tr>
                <td colspan="6" class="text-center py-4 ${messageClass}">${escapeHtml(message)}</td>
            </tr>
        `;
    }

    async function loadDevices() {
        setLoadingState();

        try {
            const response = await fetch(API_ENDPOINTS.devices);

            if (!response.ok) {
                throw new Error(`Request failed with status ${response.status}`);
            }

            const payload = await response.json();

            if (payload.status !== "success") {
                setMessageState(`Server error: ${payload.message || "Unknown error"}`, true);
                return;
            }

            renderDeviceRows(Array.isArray(payload.data) ? payload.data : []);
        } catch (error) {
            console.error("Failed to load devices:", error);
            setMessageState("Lost connection to API server!", true);
        }
    }

    function renderDeviceRows(devices) {
        if (!devices.length) {
            setMessageState("No devices found on the network.");
            return;
        }

        const rows = devices.map((device) => createDeviceRowMarkup(device)).join("");
        dom.deviceList.innerHTML = rows;
    }

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

    function createStatusBadgeMarkup(isBlocked, isOnline) {
        if (isBlocked) {
            return '<span class="badge bg-danger"><i class="fas fa-lock me-1"></i>Blocked</span>';
        }

        if (isOnline) {
            return '<span class="badge bg-success"><i class="fas fa-globe me-1"></i>Online</span>';
        }

        return '<span class="badge bg-secondary"><i class="fas fa-moon me-1"></i>Offline</span>';
    }

    function createActionButtonMarkup(isBlocked, macAddress) {
        const action = isBlocked ? "unblock" : "block";
        const icon = isBlocked ? "fa-unlock" : "fa-ban";
        const text = isBlocked ? "Unblock" : "Block MAC";
        const buttonClass = isBlocked ? "btn-outline-success" : "btn-outline-danger";

        return `
            <button
                type="button"
                class="btn btn-sm ${buttonClass}"
                data-action="${action}"
                data-mac="${escapeHtml(macAddress)}"
            >
                <i class="fas ${icon} me-1"></i>${text}
            </button>
        `;
    }

    async function toggleBlock(mac, action) {
        const endpoint = action === "block" ? API_ENDPOINTS.block : API_ENDPOINTS.unblock;

        try {
            const response = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mac }),
            });

            if (!response.ok) {
                throw new Error(`Request failed with status ${response.status}`);
            }

            const payload = await response.json();

            if (payload.status !== "success") {
                alert(`Error: ${payload.message || "Unknown error"}`);
                return;
            }

            await loadDevices();
        } catch (error) {
            console.error("Failed to update firewall rule:", error);
            alert("Cannot connect to the iptables command server!");
        }
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }
})();
