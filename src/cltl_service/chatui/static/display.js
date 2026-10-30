/*
 * The Display tab.
 *
 * Polls /chat/display, which is side-effect free for the reason /chat/scenario
 * is: a poller on /chat/current would keep a chat alive for as long as the page
 * is open. The service has already decided which urls may be shown; this only
 * draws them. The newest page is the one on view, and a person can go back to an
 * older one from the list until the next page arrives.
 *
 * Every name is written with textContent and every url through the frame's src
 * and the link's href, never as markup.
 *
 * The history belongs to a scenario. When the scenario changes, or goes away,
 * the list goes with it, as it does on the server.
 */
(function () {
    "use strict";

    var INTERVAL = 1000;
    var DEFAULT_LABEL = "Display";

    // Served from <mount>/static/display.js: two segments, as in chat.js.
    var restPath = window.location.pathname.split("/").slice(0, -2).join("/");

    var tab, label, badge, panel, title, pages, link, frame, status;
    var lastSequence = null;
    var scenarioId = null;
    var entries = [];

    document.addEventListener("DOMContentLoaded", function () {
        tab = document.getElementById("tab-display");
        if (!tab) {
            return;
        }

        label = document.getElementById("display-tab-label");
        badge = document.getElementById("display-badge");
        panel = document.getElementById("display");
        title = document.getElementById("display-title");
        pages = document.getElementById("display-history");
        link = document.getElementById("display-open");
        frame = document.getElementById("display-frame");
        status = document.getElementById("display-status");

        get("/config").then(function (config) {
            if (!config.display_enabled) {
                return;
            }

            tab.addEventListener("click", function () {
                badge.hidden = true;
            });
            pages.addEventListener("change", onChoose);
            poll();
        }, function (error) {
            console.log("Could not read the chat UI configuration:", error);
        });
    });

    function poll() {
        get("/chat/display").then(function (data) {
            if (data.scenario_id !== scenarioId) {
                scenarioId = data.scenario_id;
                lastSequence = null;
            }

            if (data.last_sequence !== lastSequence) {
                lastSequence = data.last_sequence;
                apply(data.entries);
            }
        }, function (error) {
            console.log("Could not read the display:", error);
        }).then(reschedule, reschedule);
    }

    // Rescheduled from both arms, so that a throw in the success handler cannot
    // quietly end the loop.
    function reschedule() {
        setTimeout(poll, INTERVAL);
    }

    function apply(next) {
        var newest = next.length ? next[next.length - 1] : null;
        var previous = entries.length ? entries[entries.length - 1] : null;
        entries = next;

        pages.textContent = "";
        // Newest first, so the list reads like the order things were shown in.
        next.slice().reverse().forEach(function (entry) {
            var option = document.createElement("option");
            option.value = entry.url;
            option.textContent = entry.name;
            pages.appendChild(option);
        });
        pages.disabled = !next.length;

        if (!newest) {
            show(null);
            return;
        }

        pages.value = newest.url;
        show(newest);

        // Do not take the person's tab away from the chat or the annotator.
        if ((!previous || previous.url !== newest.url) && panel.hidden) {
            badge.hidden = false;
        }
    }

    function onChoose() {
        var chosen = entries.filter(function (entry) {
            return entry.url === pages.value;
        })[0];
        if (chosen) {
            show(chosen, true);
        }
    }

    // The tab is named after the page on view only while the person has not
    // gone back to an older one, which is the same page the tab names.
    function show(entry, chosen) {
        var name = entry ? entry.name : DEFAULT_LABEL;
        title.textContent = name;
        label.textContent = chosen ? label.textContent : name;
        link.hidden = !entry;

        if (!entry) {
            frame.removeAttribute("src");
            link.removeAttribute("href");
            status.textContent = "Nothing to show yet.";
            return;
        }

        if (frame.getAttribute("src") !== entry.url) {
            frame.src = entry.url;
        }
        link.href = entry.url;
        status.textContent = "";
    }

    // -- REST ---------------------------------------------------------------

    // Two-argument `then(onOk, onError)` rather than `.then().catch()`, for the
    // reason chat.js documents.
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
