/*
 * The status bar.
 *
 * Polls /chat/status, which is side-effect free for the reason /chat/scenario
 * is: a poller on /chat/current would keep a chat alive for as long as the page
 * is open. The service decides which entry the bar shows (highest level, then
 * newest, among those not expired, ended or replaced); this only draws it, and
 * appends the rows the timeline has not seen yet.
 *
 * The timeline belongs to a scenario. When the scenario changes, or goes away,
 * the rows go with it, as they do on the server.
 */
(function () {
    "use strict";

    var INTERVAL = 1000;

    // Served from <mount>/static/status.js: two segments, as in chat.js.
    var restPath = window.location.pathname.split("/").slice(0, -2).join("/");

    var bar, toggle, timeline, level, source, message, progress;
    var nextSequence = 0;
    var scenarioId = null;

    document.addEventListener("DOMContentLoaded", function () {
        bar = document.getElementById("status-bar");
        if (!bar) {
            return;
        }

        toggle = document.getElementById("status-toggle");
        timeline = document.getElementById("status-timeline");
        level = document.getElementById("status-level");
        source = document.getElementById("status-source");
        message = document.getElementById("status-message");
        progress = document.getElementById("status-progress");

        get("/config").then(function (config) {
            if (!config.status_enabled) {
                return;
            }

            bar.hidden = false;
            toggle.addEventListener("click", onToggle);
            showCurrent(null);
            poll();
        }, function (error) {
            console.log("Could not read the chat UI configuration:", error);
        });
    });

    function onToggle() {
        var open = timeline.hidden;
        timeline.hidden = !open;
        toggle.setAttribute("aria-expanded", String(open));
        if (open) {
            timeline.scrollTop = timeline.scrollHeight;
        }
    }

    function poll() {
        get("/chat/status?from=" + nextSequence).then(function (data) {
            if (data.scenario_id !== scenarioId) {
                scenarioId = data.scenario_id;
                reset();
                // The sequence is the server's, not ours, once rows are gone.
                return get("/chat/status?from=0").then(apply);
            }

            apply(data);
        }, function (error) {
            console.log("Could not read the status:", error);
        }).then(reschedule, reschedule);
    }

    function apply(data) {
        if (data.events.length) {
            append(data.events);
        }
        nextSequence = data.last_sequence + 1;
        showCurrent(data.current);
    }

    function reset() {
        nextSequence = 0;
        timeline.textContent = "";
    }

    function append(events) {
        var atBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 8;

        events.forEach(function (event) {
            timeline.appendChild(row(event));
        });

        if (atBottom) {
            timeline.scrollTop = timeline.scrollHeight;
        }
    }

    function row(event) {
        var item = document.createElement("li");
        if (event.resolved) {
            item.className = "cltl-resolved";
        }

        var dot = document.createElement("span");
        dot.className = "status-level";
        dot.setAttribute("data-level", event.level);

        var time = document.createElement("span");
        time.className = "status-time";
        time.textContent = new Date(event.time * 1000).toLocaleTimeString();

        var who = document.createElement("span");
        who.className = "status-source";
        who.textContent = event.source;

        var text = document.createElement("span");
        text.className = "status-text";
        text.textContent = event.message
            + (event.progress === null ? "" : " (" + Math.round(event.progress * 100) + "%)");

        [dot, time, who, text].forEach(function (part) {
            item.appendChild(part);
        });

        return item;
    }

    // Everything from the service goes in through textContent, never innerHTML:
    // a message is whatever some module chose to say.
    function showCurrent(current) {
        toggle.classList.toggle("cltl-idle", !current);
        level.setAttribute("data-level", current ? current.level : "none");
        source.textContent = current ? current.source : "";
        message.textContent = current ? current.message : "No status";
        message.title = current ? current.message : "";

        var determinate = current && current.progress !== null;
        progress.hidden = !determinate;
        if (determinate) {
            progress.value = current.progress;
        }
    }

    function reschedule() {
        setTimeout(poll, INTERVAL);
    }

    // Two-argument `then(onOk, onError)`, for the reason chat.js documents.
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
