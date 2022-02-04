$(document).ready(function() {
    const pollInterval = 1000;
    const animationTime = 0;
    let restPath = window.location.pathname.split('/').slice(0, -2).join('/');

    var agentId = false;
    var chatId = false;
    var turn = 0;
    var chatSequence = Number.MIN_SAFE_INTEGER;
    var utteranceIds = new Set();

    let chatWindow = new Bubbles(
        document.getElementById("chat"),
        "chatWindow",
        {
            inputCallbackFn: function (chatObject) {
                turn += 1;
                let input = chatObject.input;
                $.post(restPath + "/chat/" + chatId, input)
                    .done(utteranceId => utteranceIds.add(utteranceId));
            },
            animationTime: animationTime
        }
    );

    let initChat = function () {
        $.get(restPath + "/chat/current")
            .done(data => {
                chatId = data.id;
                agentId = data.agent;
                console.log("Retrieved chat ID:", chatId, agentId);
        });
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
            // New turn pair if first or speaker is agent and the last turn pair has user utterances
            if (turns.length === 0 || (utterance.speaker === agentId && turns[turns.length-1].other.length)) {
                turns.push({agent: [], other: []});
            }

            let lastTurn = turns[turns.length-1];
            let turnPart = utterance.speaker === agentId ? lastTurn.agent : lastTurn.other;
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
        $.get(restPath + "/chat/" + chatId + "?from=" + (chatSequence  + 1))
            .then(talk, () => setTimeout(poll, pollInterval + (animationTime || 0)));
    }

    let initialConvo = {
        ice: {says: [""], reply: []},
        silence: {says: [], reply: []}
    };

    initChat()
    chatWindow.talk(initialConvo);
    poll();
});