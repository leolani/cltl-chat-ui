/*
 * The stop button.
 *
 * It types the deployment's stop phrase into the chat box and presses Enter, so
 * the phrase takes exactly the path a person's own message does: it is echoed
 * into the transcript and posted as an utterance. What stops the scenario is
 * cltl-context's keyword service recognising that utterance, not anything here.
 *
 * That has two consequences. The phrase has to be one of the deployment's
 * keywords, and the keyword service ignores it outside the `eliza` intention, so
 * a press while the conversation is still being set up does nothing. The page
 * only knows whether a scenario exists, so that is what the button follows.
 */
(function () {
    "use strict";

    var SCENARIO_INTERVAL = 3000;

    // Served from <mount>/static/stop.js: two segments, as in chat.js.
    var restPath = window.location.pathname.split("/").slice(0, -2).join("/");

    var button = null;
    var phrase = null;

    document.addEventListener("DOMContentLoaded", function () {
        button = document.getElementById("stop-scenario");
        if (!button) {
            return;
        }

        get("/config").then(function (config) {
            phrase = config.stop_phrase || null;
            if (!phrase) {
                return;
            }

            button.hidden = false;
            button.addEventListener("click", stop);
            pollScenario();
        }, function (error) {
            console.log("Could not read the chat UI configuration:", error);
        });
    });

    function stop() {
        var input = document.querySelector("#chat .input-wrap textarea");
        if (!input || !phrase) {
            return;
        }

        // Bubbles listens for the legacy keyCode, which the KeyboardEvent
        // constructor does not populate.
        var enter = new KeyboardEvent("keypress", {key: "Enter", bubbles: true, cancelable: true});
        Object.defineProperty(enter, "keyCode", {value: 13});

        input.value = phrase;
        input.dispatchEvent(enter);
        button.disabled = true;
    }

    function pollScenario() {
        get("/chat/scenario").then(function (data) {
            button.disabled = !data.scenario_id;
        }, function (error) {
            console.log("Could not read the current scenario:", error);
        }).then(reschedule, reschedule);
    }

    function reschedule() {
        setTimeout(pollScenario, SCENARIO_INTERVAL);
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
