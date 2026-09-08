/*
 * The tabbed panel beside the conversation.
 *
 * Two things live here: which panels this deployment actually offers, and which
 * one is showing. Both were previously unanswerable — the page rendered the
 * annotator whether or not uploads were enabled, and found out from a 404.
 *
 * The Monitoring tab holds an iframe onto the page cltl-monitoring serves. It
 * is embedded rather than reimplemented because in a containerised deployment
 * that page is a different service on a different origin, and because what it
 * shows is that component's business, not this one's.
 */
(function () {
    "use strict";

    var SCENARIO_INTERVAL = 3000;

    // Served from <mount>/static/panels.js, so exactly two segments are chopped
    // to get back to the REST base. The same computation as chat.js, repeated
    // rather than read off `window.cltlChat`: this file has no other reason to
    // depend on that one's load order.
    var restPath = window.location.pathname.split("/").slice(0, -2).join("/");

    var monitoringUrl = null;
    var scenarioId = null;
    var tabs = [];
    var elements = {};

    document.addEventListener("DOMContentLoaded", function () {
        elements = {
            panel: document.getElementById("side-panel"),
            strip: document.getElementById("panel-tabs"),
            frame: document.getElementById("monitor-frame"),
            status: document.getElementById("monitor-status")
        };

        if (!elements.panel || !elements.strip) {
            return;
        }

        tabs = Array.prototype.slice.call(elements.strip.querySelectorAll("[role=tab]"))
            .map(function (tab) {
                return {tab: tab, panel: document.getElementById(tab.getAttribute("aria-controls"))};
            })
            .filter(function (entry) {
                return entry.panel;
            });

        tabs.forEach(function (entry) {
            entry.tab.addEventListener("click", function () {
                select(entry);
            });
        });
        elements.strip.addEventListener("keydown", onKeyDown);

        configure();
    });

    // -- what this deployment offers ----------------------------------------

    function configure() {
        get("/config").then(apply, function (error) {
            // A deployment too old to have the endpoint still has an annotator.
            console.log("Could not read the chat UI configuration:", error);
            apply({image_upload: true, monitoring_url: null});
        });
    }

    function apply(config) {
        monitoringUrl = config.monitoring_url || null;

        var enabled = tabs.filter(function (entry) {
            if (entry.panel.id === "annotator") {
                return config.image_upload !== false;
            }
            if (entry.panel.id === "monitor") {
                return !!monitoringUrl;
            }
            return true;
        });

        tabs.forEach(function (entry) {
            var on = enabled.indexOf(entry) !== -1;
            entry.tab.hidden = !on;
            if (!on) {
                entry.panel.hidden = true;
            }
        });

        if (!enabled.length) {
            // Nothing to put beside the conversation; let it have the width.
            elements.panel.hidden = true;
            return;
        }

        // A single tab is not a choice, so do not present one.
        elements.strip.classList.toggle("cltl-single-tab", enabled.length === 1);
        select(enabled[0]);

        if (monitoringUrl) {
            setStatus("Waiting for a conversation to start.");
            pollScenario();
        }
    }

    // -- switching ----------------------------------------------------------

    function select(selected) {
        tabs.forEach(function (entry) {
            var on = entry === selected;
            entry.tab.setAttribute("aria-selected", on ? "true" : "false");
            // The iframe is never torn down: switching away and back must not
            // reload the monitoring page or blank it while it reconnects.
            entry.panel.hidden = !on;
        });
    }

    function onKeyDown(event) {
        var step = event.key === "ArrowRight" ? 1 : (event.key === "ArrowLeft" ? -1 : 0);
        if (!step) {
            return;
        }

        var visible = tabs.filter(function (entry) {
            return !entry.tab.hidden;
        });
        var current = visible.findIndex(function (entry) {
            return entry.tab.getAttribute("aria-selected") === "true";
        });
        if (current < 0 || visible.length < 2) {
            return;
        }

        var next = visible[(current + step + visible.length) % visible.length];
        select(next);
        next.tab.focus();
        event.preventDefault();
    }

    // -- which conversation the monitor shows -------------------------------

    function pollScenario() {
        get("/chat/scenario").then(function (data) {
            update(data.scenario_id || null);
        }, function (error) {
            console.log("Could not read the current scenario:", error);
        }).then(reschedule, reschedule);
    }

    // Rescheduled from both arms, so that a throw in the success handler cannot
    // quietly end the loop.
    function reschedule() {
        setTimeout(pollScenario, SCENARIO_INTERVAL);
    }

    function update(id) {
        if (id === scenarioId) {
            return;
        }

        scenarioId = id;
        if (!scenarioId) {
            // The conversation ended. Its monitoring state went with it, so
            // showing the last frame of it would be a lie.
            elements.frame.removeAttribute("src");
            setStatus("Waiting for a conversation to start.");
            return;
        }

        elements.frame.src = monitoringUrl.replace(/\/$/, "")
            + "/static/monitoring.html?scenario=" + encodeURIComponent(scenarioId);
        setStatus("");
    }

    function setStatus(message) {
        if (elements.status) {
            elements.status.textContent = message || "";
        }
    }

    // -- REST ---------------------------------------------------------------

    // Two-argument `then(onOk, onError)` rather than `.then().catch()`, for the
    // reason chat.js documents: a trailing `catch` also fires when the success
    // handler throws, which here would schedule a second polling loop.
    function get(path) {
        return fetch(restPath + path, {headers: {"Accept": "application/json"}})
            .then(function (response) {
                return response.ok
                    ? response.json()
                    : response.text().then(function (body) {
                        return Promise.reject({status: response.status, body: body});
                    });
            });
    }
})();
