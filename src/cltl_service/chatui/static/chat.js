document.addEventListener("DOMContentLoaded", function () {
    const pollInterval = 1000;
    const animationTime = 0;
    // Exactly two segments are chopped: this script is served from
    // <mount>/static/chat.js, so anything moved into a subdirectory of static/
    // would compute the wrong REST base.
    const restPath = window.location.pathname.split('/').slice(0, -2).join('/');

    var agentId = false;
    var chatId = false;
    var turn = 0;
    var chatSequence = Number.MIN_SAFE_INTEGER;
    var utteranceIds = new Set();

    // The handle annotate.js reads: same REST base, same chat, discovered once
    // here rather than twice. Plain globals and a DOM event, because the page
    // loads ordinary <script> tags in order and there is no module system.
    const cltlChat = window.cltlChat = {restPath: restPath, chatId: null, agentId: null,
                                        scenarioId: null, ready: false};

    // Two-argument `then(onOk, onError)` rather than `.then(...).catch(...)`
    // throughout: a `catch` after a `then` also fires when the success handler
    // itself throws, which here would schedule a second polling loop on top of
    // the one `talk` has already scheduled in its `finally`, and double the
    // request rate every time it happened. jQuery's `.done().fail()` had the
    // semantics we want; this is how you get them back.
    let get = function (path) {
        return fetch(restPath + path, {headers: {"Accept": "application/json"}})
            .then(response => response.ok
                ? response.json()
                : response.text().then(body => Promise.reject({status: response.status, body: body})));
    };

    let post = function (path, body) {
        return fetch(restPath + path, {method: "POST", body: body})
            .then(response => response.ok
                ? response.text()
                : response.text().then(text => Promise.reject({status: response.status, body: text})));
    };

    let chatWindow = new Bubbles(
        document.getElementById("chat"),
        "chatWindow",
        {
            inputCallbackFn: function (chatObject) {
                turn += 1;
                post("/chat/" + chatId, chatObject.input)
                    .then(utteranceId => utteranceIds.add(utteranceId),
                          error => console.log("Could not post utterance:", error));
            },
            animationTime: animationTime
        }
    );

    let initChat = function () {
        get("/chat/current")
            .then(data => {
                chatId = data.id;
                agentId = data.agent;
                cltlChat.chatId = chatId;
                cltlChat.agentId = agentId;
                cltlChat.scenarioId = data.scenario_id;
                cltlChat.ready = true;
                console.log("Retrieved chat ID:", chatId, agentId);
                window.dispatchEvent(new CustomEvent("cltl-chat-ready", {detail: cltlChat}));
            }, error => {
                if (error.status === 307) {
                    alert("Currently there is another chat in progress, try again in " + error.body + " minutes.");
                } else {
                    console.log("Retrieved unhandled status: " + error.status);
                    // Without a chat id nothing else on the page works, so keep
                    // asking rather than leaving a dead window behind.
                    setTimeout(initChat, pollInterval);
                }
            });
        console.log("Initialized chat for", chatId, agentId, "start polling");
        setTimeout(poll, pollInterval + (animationTime || 100));
    };

    // Rich content goes down chat-bubble's `says` path, never its `reply` path:
    // `Bubbles.js` interpolates a reply's content into an onClick attribute.
    let isSays = function (utterance) {
        return utterance.speaker === agentId || utterance.content_type === "text/html";
    };

    let talk = function(utterances) {
        if (!chatId) {
            // Not initialized yet
            setTimeout(poll, pollInterval + (animationTime || 0));
            return;
        }

        var convos;
        try {
            let newUtterances = utterances.filter(utterance => !utteranceIds.has(utterance.id) && utterance.text);
            newUtterances.forEach(utterance => utteranceIds.add(utterance.id));
            chatSequence = Math.max(...utterances.map(utt => utt.sequence), chatSequence);

            let turns = groupTurns(newUtterances);
            convos = turns.map(toConversationObjects);

            convos.forEach((convo, i) =>
                setTimeout(() =>
                    chatWindow.talk(convo, Object.keys(convo)[0]), i * 500));
        } finally {
            let timeout = ((convos && convos.length) || 0) * 500 + pollInterval + (animationTime || 0);
            setTimeout(poll, timeout);
        }
    }

    let groupTurns = function (utterances) {
        utterances.sort((a, b) => a.timestamp - b.timestamp);
        let turnAggregator = function(turns, utterance) {
            // New turn pair if first or the utterance is rendered on the agent
            // side and the last turn pair has user utterances
            if (turns.length === 0 || (isSays(utterance) && turns[turns.length-1].other.length)) {
                turns.push({agent: [], other: []});
            }

            let lastTurn = turns[turns.length-1];
            let turnPart = isSays(utterance) ? lastTurn.agent : lastTurn.other;
            turnPart.push(utterance);

            return turns;
        };

        return utterances.reduce(turnAggregator, []);
    };

    let toConversationObjects = function(currentTurn) {
        turn += 1;

        // The Chat UI accepts blocks of agent utterances - user utterances.
        // Agent utterances are submitted as text array in 'says'
        // User utterances are submitted as question-answer replies
        let agent = currentTurn.agent.map(utt => `${utt.speaker}> ${utt.text}`);
        let other = currentTurn.other.map(utt => `${utt.speaker}> ${utt.text}`).join(" |");

        convo = {}
        convo[turn] = {
            says: agent,
            reply: (other && [{question: other, answer: "silence"}]) || []
        };

        return convo;
    };

    let poll = function () {
        if (!chatId) {
            setTimeout(poll, pollInterval + (animationTime || 0));
            return;
        }

        get("/chat/" + chatId + "?from=" + (chatSequence + 1))
            .then(talk, error => {
                if (error.status === 404) {
                    console.log("Terminated chat");
                } else {
                    setTimeout(poll, pollInterval + (animationTime || 0));
                }
            });
    }

    let initialConvo = {
        ice: {says: [""], reply: []},
        silence: {says: [], reply: []}
    };

    initChat();
    chatWindow.talk(initialConvo);
});
