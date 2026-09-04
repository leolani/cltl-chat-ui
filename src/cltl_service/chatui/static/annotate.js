/*
 * Image upload and region annotation, beside the chat.
 *
 * Drawing, hit-testing, resize handles, selection, coordinate mapping and
 * undo/redo all come from Annotorious (static/annotorious/, vendored UMD build,
 * global `Annotorious`). What is left here is the part Annotorious deliberately
 * does not have: a file input, a label per box, a delete button, and the
 * mapping from its annotations to the REST API's `regions`.
 *
 * Coordinates from `selector.geometry.bounds` are in SOURCE-IMAGE pixels, not
 * CSS pixels: the overlay's viewBox is naturalWidth x naturalHeight and pointer
 * offsets are divided back through it. They are floats, hence the rounding.
 * Never read the W3C FragmentSelector instead — a rectangle that has been
 * rotated with the (unsuppressable) rotation handle serialises to an
 * SvgSelector, while `geometry.bounds` is always the axis-aligned box.
 */
(function () {
    "use strict";

    var anno = null;
    var objectUrl = null;
    var upload = null;          // {id, url, width, height} of the current upload
    var labels = {};            // annotation id -> label, mirrored into bodies

    var elements = {};

    document.addEventListener("DOMContentLoaded", function () {
        elements = {
            panel: document.getElementById("annotator"),
            file: document.getElementById("annotate-file"),
            image: document.getElementById("annotate-image"),
            regions: document.getElementById("annotate-regions"),
            submit: document.getElementById("annotate-submit"),
            clear: document.getElementById("annotate-clear"),
            status: document.getElementById("annotate-status"),
            empty: document.getElementById("annotate-empty")
        };

        if (!elements.file || !elements.image) {
            return;
        }
        if (typeof Annotorious === "undefined") {
            setStatus("The annotation library did not load.", true);
            return;
        }

        elements.file.addEventListener("change", onFileChosen);
        elements.submit.addEventListener("click", onSubmit);
        elements.clear.addEventListener("click", onClear);
        elements.image.addEventListener("load", onImageLoaded);

        setEnabled(false);
    });

    // -- REST ---------------------------------------------------------------

    function chat() {
        return window.cltlChat || {};
    }

    function chatPath(suffix) {
        var current = chat();
        return current.restPath + "/chat/" + current.chatId + suffix;
    }

    function withChat(action) {
        if (chat().chatId) {
            action();
            return;
        }
        // chat.js discovers the chat id asynchronously; the panel is usable
        // before it arrives.
        window.addEventListener("cltl-chat-ready", function ready() {
            window.removeEventListener("cltl-chat-ready", ready);
            action();
        });
    }

    // -- uploading ----------------------------------------------------------

    function onFileChosen() {
        var file = elements.file.files && elements.file.files[0];
        if (!file) {
            return;
        }

        resetAnnotator();
        upload = null;
        setEnabled(false);
        setStatus("Loading " + file.name + "...");

        if (objectUrl) {
            URL.revokeObjectURL(objectUrl);
        }
        objectUrl = URL.createObjectURL(file);
        elements.image.dataset.file = file.name;
        elements.image.src = objectUrl;
    }

    function onImageLoaded() {
        var image = elements.image;
        if (!image.naturalWidth || !image.naturalHeight) {
            setStatus("That file could not be displayed as an image.", true);
            return;
        }

        show(elements.empty, false);
        show(image, true);
        createAnnotator();
        sendImage();
    }

    function sendImage() {
        var file = elements.file.files && elements.file.files[0];
        if (!file) {
            return;
        }

        withChat(function () {
            var query = "?width=" + elements.image.naturalWidth +
                        "&height=" + elements.image.naturalHeight;
            fetch(chatPath("/image" + query), {
                method: "POST",
                headers: {"Content-Type": file.type},
                body: file
            }).then(function (response) {
                if (!response.ok) {
                    return response.text().then(function (body) {
                        throw new Error(response.status + " " + (body || response.statusText));
                    });
                }
                return response.json();
            }).then(function (stored) {
                upload = stored;
                setEnabled(true);
                setStatus("Drag on the image to mark a region, then Submit.");
            }).catch(function (error) {
                setStatus("Upload failed: " + error.message, true);
            });
        });
    }

    // -- annotator ----------------------------------------------------------

    function createAnnotator() {
        // Destroyed and re-created for every upload: the overlay's viewBox is
        // captured at init and does not follow a later src swap, and an
        // annotator created before the image has loaded gets viewBox="0 0 0 0"
        // and divides by zero.
        resetAnnotator();

        anno = Annotorious.createImageAnnotator(elements.image, {
            // Without this, `createAnnotation` does not fire until the shape is
            // deselected, so a freshly drawn box has no row to label.
            autoSave: true,
            drawingMode: "drag",
            userSelectAction: "EDIT"
        });
        anno.setDrawingTool("rectangle");

        anno.on("createAnnotation", function (annotation) {
            renderRegions();
            focusLabel(annotation.id);
        });
        anno.on("deleteAnnotation", function (annotation) {
            delete labels[annotation.id];
            renderRegions();
        });
        anno.on("selectionChanged", function (selected) {
            highlight(selected && selected.length ? selected[0].id : null);
        });

        labels = {};
        renderRegions();
    }

    function resetAnnotator() {
        if (anno) {
            anno.destroy();
            anno = null;
        }
        labels = {};
        renderRegions();
    }

    // -- the region list ----------------------------------------------------

    function annotations() {
        return anno ? anno.getAnnotations() : [];
    }

    function boundsOf(annotation) {
        var selector = annotation.target && annotation.target.selector;
        var geometry = selector && selector.geometry;

        return geometry && geometry.bounds;
    }

    function labelOf(annotation) {
        if (Object.prototype.hasOwnProperty.call(labels, annotation.id)) {
            return labels[annotation.id];
        }
        var bodies = annotation.bodies || [];
        for (var i = 0; i < bodies.length; i++) {
            if (bodies[i] && bodies[i].value) {
                return bodies[i].value;
            }
        }

        return "";
    }

    function renderRegions() {
        var list = elements.regions;
        if (!list) {
            return;
        }
        list.textContent = "";

        var current = annotations();
        current.forEach(function (annotation, index) {
            list.appendChild(regionRow(annotation, index));
        });

        if (elements.submit) {
            elements.submit.disabled = !upload;
        }
    }

    function regionRow(annotation, index) {
        var bounds = boundsOf(annotation);
        var row = document.createElement("li");
        row.className = "cltl-region";
        row.dataset.annotation = annotation.id;

        var ordinal = document.createElement("span");
        ordinal.className = "cltl-region-index";
        ordinal.textContent = String(index + 1);

        var input = document.createElement("input");
        input.type = "text";
        input.className = "cltl-region-label";
        input.placeholder = "What is this?";
        input.value = labelOf(annotation);
        input.addEventListener("input", function () {
            labels[annotation.id] = input.value;
        });
        input.addEventListener("change", function () {
            storeLabel(annotation.id, input.value);
        });
        input.addEventListener("focus", function () {
            if (anno) {
                anno.setSelected(annotation.id);
            }
        });

        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "cltl-region-delete";
        remove.title = "Remove this region";
        remove.textContent = "×";
        remove.addEventListener("click", function () {
            if (anno) {
                anno.removeAnnotation(annotation.id);
            }
            delete labels[annotation.id];
            renderRegions();
        });

        var coordinates = document.createElement("span");
        coordinates.className = "cltl-region-bounds";
        coordinates.textContent = bounds
            ? Math.round(bounds.minX) + ", " + Math.round(bounds.minY) + " – " +
              Math.round(bounds.maxX) + ", " + Math.round(bounds.maxY)
            : "";

        row.appendChild(ordinal);
        row.appendChild(input);
        row.appendChild(remove);
        row.appendChild(coordinates);

        return row;
    }

    function storeLabel(annotationId, value) {
        labels[annotationId] = value;
        if (!anno) {
            return;
        }
        var annotation = anno.getAnnotationById(annotationId);
        if (!annotation) {
            return;
        }
        // The native model's own place for a label. Kept in step with `labels`
        // so that either is enough to submit from.
        anno.updateAnnotation(Object.assign({}, annotation, {
            bodies: [{
                id: annotationId + "-label",
                annotation: annotationId,
                purpose: "commenting",
                value: value
            }]
        }));
    }

    function focusLabel(annotationId) {
        if (!elements.regions) {
            return;
        }
        var row = elements.regions.querySelector('[data-annotation="' + annotationId + '"]');
        var input = row && row.querySelector(".cltl-region-label");
        if (input) {
            input.focus();
        }
        highlight(annotationId);
    }

    function highlight(annotationId) {
        if (!elements.regions) {
            return;
        }
        var rows = elements.regions.querySelectorAll(".cltl-region");
        for (var i = 0; i < rows.length; i++) {
            rows[i].classList.toggle("cltl-region-selected",
                                     rows[i].dataset.annotation === annotationId);
        }
    }

    // -- submitting ---------------------------------------------------------

    function regions() {
        return annotations().map(function (annotation) {
            var bounds = boundsOf(annotation);
            if (!bounds) {
                return null;
            }

            return {
                x0: Math.round(bounds.minX),
                y0: Math.round(bounds.minY),
                x1: Math.round(bounds.maxX),
                y1: Math.round(bounds.maxY),
                label: labelOf(annotation)
            };
        }).filter(Boolean);
    }

    function onSubmit() {
        if (!upload) {
            setStatus("Choose an image first.", true);
            return;
        }

        var body = {regions: regions()};
        setEnabled(false);
        setStatus("Submitting " + body.regions.length + " region(s)...");

        fetch(chatPath("/image/" + upload.id + "/annotations"), {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(body)
        }).then(function (response) {
            if (!response.ok) {
                return response.text().then(function (text) {
                    throw new Error(response.status + " " + (text || response.statusText));
                });
            }
            return response.json();
        }).then(function (result) {
            setStatus("Recorded " + result.mentions + " region(s); the image is in the chat.");
            clearImage();
        }).catch(function (error) {
            setEnabled(true);
            setStatus("Submit failed: " + error.message, true);
        });
    }

    function onClear() {
        if (anno) {
            anno.clearAnnotations();
        }
        labels = {};
        renderRegions();
        setStatus("Cleared the regions; the image is still here.");
    }

    function clearImage() {
        resetAnnotator();
        upload = null;
        elements.file.value = "";
        elements.image.removeAttribute("src");
        show(elements.image, false);
        show(elements.empty, true);
        if (objectUrl) {
            URL.revokeObjectURL(objectUrl);
            objectUrl = null;
        }
        setEnabled(false);
    }

    // -- chrome -------------------------------------------------------------

    function setEnabled(enabled) {
        if (elements.submit) {
            elements.submit.disabled = !enabled;
        }
        if (elements.clear) {
            elements.clear.disabled = !enabled;
        }
    }

    function setStatus(message, isError) {
        if (!elements.status) {
            return;
        }
        elements.status.textContent = message || "";
        elements.status.classList.toggle("cltl-error", !!isError);
    }

    function show(element, visible) {
        if (element) {
            element.style.display = visible ? "" : "none";
        }
    }
})();
