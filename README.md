# cltl-chat-ui

Simple text based chat UI.

The chat UI can be used to display text signals and create text signals from user input.

This repository is a component of the [Leolani framework](https://github.com/leolani/cltl-combot).
For usage of the component within the framework see the instructions there.


## Optional features

The chat UI has two optional features that let other modules show something to the person chatting: a
**status bar** and a **Display tab**. Each is off unless its topic is configured.

Both are bound to the running scenario. Only events published with `Event.for_scenario_payload` for the
scenario that is running are kept, everything else is dropped, and what was kept is cleared on
`ScenarioStopped`.

`config/default.config` uses legacy topic names. A deployment must set the topics below to the ones its
publishers actually use.

### Status bar

A bar under the chat window shows what the backend's modules report as `StatusEvent`s
(`cltl.combot.event.status`). It shows one entry: among those that have not expired, ended or been replaced,
the highest level wins (`error` > `warning` > `info`), and the newest of equals. Clicking the bar opens the
timeline of every event in the scenario.

```ini
[cltl.chat-ui]
status_history: 200                   # timeline rows kept (default 200)

[cltl.chat-ui.events]
topic_status: cltl.topic.status       # empty (the default) leaves the bar out; /chat/status then returns 404
```

| `StatusEvent` field | Meaning |
|---|---|
| `message`, `source` | What the person reads. Both are required. |
| `level` | `info` (default), `warning` or `error`. |
| `progress` | 0 to 1, shown as a progress bar. |
| `ttl` | Seconds until the entry goes away, counted from when the chat UI received it. |
| `key` | Names a status so that a later event can replace or end it. |
| `resolved` | Ends the status with the same `key`. Needs a `key`. |
| `persistent` | A lasting line in the chat history instead of a bar entry. Cannot be combined with `ttl`, `progress` or `resolved`. |

```python
from cltl.combot.event.status import StatusEvent
from cltl.combot.infra.event import Event

event_bus.publish(status_topic, Event.for_scenario_payload(
    scenario_id, StatusEvent("Loading the speech model", "asr", progress=0.5, key="asr.model")))
event_bus.publish(status_topic, Event.for_scenario_payload(
    scenario_id, StatusEvent("Speech model loaded", "asr", key="asr.model", resolved=True)))
```

An event without a `key` cannot be ended explicitly, so give it a `ttl`. Messages are always shown as text,
never as markup. See `docs/plans/chat-ui-status-bar.md` in the cltl-dev repository.

### Display tab

A tab beside the conversation shows a page that another module asked for, as a `DisplayEvent`
(`cltl.combot.event.display`) with a `url` and a `name`.

* The newest page is the one on view. A dropdown lists every page shown in the scenario, and choosing an older
  one switches the frame to it.
* The tab reads "Display" until the first event, then takes the name of the latest one.
* A new page does not take the person away from the tab they are on. The tab shows a "new" badge instead.
* Showing a URL again moves it to the end of the list instead of adding a second entry.
* **Open in new tab** is always offered, because many sites send `X-Frame-Options` or `frame-ancestors` and
  refuse to be framed.

```ini
[cltl.chat-ui]
display_history: 50                   # pages remembered per scenario (default 50)
display_allowed_hosts: docs.example.org, charts.example.org   # besides localhost, comma separated

[cltl.chat-ui.events]
topic_display: cltl.topic.display     # empty (the default) leaves the tab out; /chat/display then returns 404
```

```python
from cltl.combot.event.display import DisplayEvent
from cltl.combot.infra.event import Event

event_bus.publish(display_topic, Event.for_scenario_payload(
    scenario_id, DisplayEvent("http://localhost:8000/monitoring/", "Monitoring")))
```

**What may be shown.** Only `http` and `https` URLs on `localhost`, `127.0.0.1`, `::1` or a host in
`display_allowed_hosts` are shown, and a URL with credentials in it is refused. The host is compared
exactly, ignoring the port, so `sub.example.org` does not match `example.org`. Anything else is logged as a
warning and dropped before it reaches the browser. The frame has no `sandbox`, so this list is the only
control over what it loads.

**Reachability.** The URL is loaded by the person's browser, not by the chat UI, and is never rewritten. In
Docker Compose that means a published host port, not a service name.

See `docs/plans/chat-ui-display-tab.md` in the cltl-dev repository.

### Trying them

From the root of the cltl-dev repository, which publishes example events since nothing in the platform does yet:

```bash
make -C integration demo-chatui-status
make -C integration demo-chatui-display
```


## Contributing

Contributions are what make the open source community such an amazing place to be learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request


<!-- LICENSE -->
## License

Distributed under the MIT License. See [`LICENSE`](https://github.com/leolani/cltl-combot/blob/main/LICENCE) for more information.

<!-- CONTACT -->
## Authors

* [Taewoon Kim](https://tae898.github.io/)
* [Thomas Baier](https://www.linkedin.com/in/thomas-baier-05519030/)
* [Selene Báez Santamaría](https://selbaez.github.io/)
* [Piek Vossen](https://github.com/piekvossen)
