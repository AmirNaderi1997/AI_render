/* global app, File */
var AIRenderBridge = AIRenderBridge || {};

// Safe wrapper to ensure globals are available
(function (bridge) {
    "use strict";

    // Safely get globals
    var appAvailable = false;
    var fileAvailable = false;
    var premiereVersion = "unknown";

    try {
        if (typeof app !== 'undefined' && app !== null) {
            appAvailable = true;
            try { premiereVersion = String(app.version || "unknown"); } catch (_) {}
        }
    } catch (_) { }

    try {
        if (typeof File !== 'undefined' && File !== null) {
            fileAvailable = true;
        }
    } catch (_) { }

    function normalize(path) {
        return String(path || "").replace(/\\/g, "/").toLowerCase();
    }

    function eachItem(parent, visit) {
        if (!parent || !parent.children) return;
        for (var i = 0; i < parent.children.numItems; i++) {
            var child = parent.children[i];
            visit(child);
            if (child && child.type === 2) eachItem(child, visit);
        }
    }

    function findItemsByMediaPath(path) {
        var wanted = normalize(path), found = [];
        try {
            eachItem(app.project.rootItem, function (item) {
                try {
                    if (item && item.getMediaPath && normalize(item.getMediaPath()) === wanted) found.push(item);
                } catch (_) {}
            });
        } catch (_) {}
        return found;
    }

    function findBin(name) {
        var found = null;
        try {
            eachItem(app.project.rootItem, function (item) {
                if (!found && item && item.type === 2 && item.name === name) found = item;
            });
        } catch (_) {}
        return found;
    }

    function ensureBin(name) {
        try {
            var bin = findBin(name);
            if (!bin) {
                app.project.rootItem.createBin(name);
                bin = findBin(name);
            }
            return bin || app.project.rootItem;
        } catch (_) {
            return app.project.rootItem;
        }
    }

    function findSequences(name) {
        var found = [];
        try {
            if (!app.project || !app.project.sequences) return found;
            for (var i = 0; i < app.project.sequences.numSequences; i++) {
                if (app.project.sequences[i].name === name) found.push(app.project.sequences[i]);
            }
        } catch (_) {}
        return found;
    }

    function importOne(path, targetBin) {
        try {
            var existing = findItemsByMediaPath(path);
            if (existing.length) return { item: existing[0], imported: false, duplicates: existing.length - 1 };
            var ok = app.project.importFiles([path], true, targetBin, false);
            var after = findItemsByMediaPath(path);
            return { item: after.length ? after[0] : null, imported: !!ok && after.length > 0, duplicates: Math.max(0, after.length - 1) };
        } catch (e) {
            return { item: null, imported: false, duplicates: 0, error: String(e) };
        }
    }

    function trackCount(collection) {
        try {
            return collection && typeof collection.numTracks === "number" ? collection.numTracks : 0;
        } catch (_) {
            return 0;
        }
    }

    function mediaOccurrencesOnTimeline(sequence, path) {
        try {
            var wanted = normalize(path), count = 0, groups = [sequence.videoTracks, sequence.audioTracks];
            for (var g = 0; g < groups.length; g++) {
                var tracks = groups[g];
                if (!tracks) continue;
                for (var t = 0; t < tracks.numTracks; t++) {
                    var clips = tracks[t].clips;
                    if (!clips) continue;
                    for (var c = 0; c < clips.numItems; c++) {
                        try {
                            var item = clips[c].projectItem;
                            if (item && item.getMediaPath && normalize(item.getMediaPath()) === wanted) count++;
                        } catch (_) {}
                    }
                }
            }
            return count;
        } catch (_) {
            return 0;
        }
    }

    function baseReceipt(command) {
        var musicPath = (command.files && command.files.music) || "";
        try {
            return {
                protocol_version: command.protocol_version,
                operation_id: command.operation_id,
                job_id: command.job_id,
                artifact_identity: command.artifact_identity,
                premiere_version: premiereVersion,
                project: { requested_path: command.expected_project_path, active_path: "none", opened: false, saved: false },
                sequence: { name: command.sequence_name, sequence_id: "unobserved", imported: false, timeline_open: false, video_track_count: 0, audio_track_count: 0 },
                render_reference: { media_path: command.files.render, imported: false, placed_on_editable_timeline: false },
                captions: { media_path: command.files.captions, imported: false, track_created: false, placed: false },
                music: musicPath ? { media_path: musicPath, imported: false, placed_on_timeline: false } : null,
                duplicates: { sequence: 0, render_reference: 0, captions: 0 },
                warnings: [], errors: []
            };
        } catch (e) {
            return {
                protocol_version: command.protocol_version || 1,
                operation_id: command.operation_id || "unknown",
                job_id: command.job_id || "unknown",
                artifact_identity: command.artifact_identity || {},
                premiere_version: premiereVersion,
                project: { requested_path: command.expected_project_path || "", active_path: "none", opened: false, saved: false },
                sequence: { name: "", sequence_id: "unobserved", imported: false, timeline_open: false, video_track_count: 0, audio_track_count: 0 },
                render_reference: { media_path: "", imported: false, placed_on_editable_timeline: false },
                captions: { media_path: "", imported: false, track_created: false, placed: false },
                music: null,
                duplicates: { sequence: 0, render_reference: 0, captions: 0 },
                warnings: [], errors: [String(e)]
            };
        }
    }

    bridge.execute = function (commandJson) {
        // Validate input
        if (!commandJson || typeof commandJson !== "string") {
            return JSON.stringify({ errors: ["Invalid input: command must be a JSON string"] });
        }

        // Check prerequisites
        if (!appAvailable) {
            return JSON.stringify({ errors: ["Premiere app not accessible. Restart Premiere and try again."] });
        }
        if (!fileAvailable) {
            return JSON.stringify({ errors: ["File constructor not accessible. Restart Premiere and try again."] });
        }

        var command, receipt;

        // Parse command
        try {
            command = JSON.parse(commandJson);
        } catch (parseError) {
            return JSON.stringify({ errors: ["Invalid AI Render command: " + String(parseError)] });
        }

        // Create receipt
        try {
            receipt = baseReceipt(command);
        } catch (receiptError) {
            return JSON.stringify({ errors: ["Failed to create receipt: " + String(receiptError)] });
        }

        if (!command || !receipt) {
            return JSON.stringify({ errors: ["Failed to initialize command or receipt"] });
        }

        // Main execution with comprehensive error handling
        try {
            // Verify app is still available
            if (typeof app === 'undefined' || !app || !app.project) {
                receipt.errors.push("No Premiere project open. Create or open a project first.");
                return JSON.stringify(receipt);
            }

            receipt.project.active_path = app.project ? String(app.project.path) : "none";

            // Verify the correct project is open (do NOT call app.openDocument — it resets the
            // ExtendScript engine mid-execution, causing an unrecoverable EvalScript error).
            if (!app.project) {
                receipt.errors.push("No Premiere project is open. Open the AI Render project file first.");
                return JSON.stringify(receipt);
            }

            if (normalize(app.project.path) !== normalize(command.expected_project_path)) {
                receipt.errors.push(
                    "Wrong project open. Please open: " + command.expected_project_path +
                    " (currently open: " + String(app.project.path) + ")"
                );
                return JSON.stringify(receipt);
            }

            receipt.project.opened = true;

            // Handle sequences
            var sequences = findSequences(command.sequence_name);
            if (!sequences.length && command.requested_actions.import_sequence) {
                try {
                    app.project.importFiles([command.files.xml], true, app.project.rootItem, false);
                    sequences = findSequences(command.sequence_name);
                    receipt.sequence.imported = sequences.length > 0;
                } catch (importError) {
                    receipt.errors.push("Could not import sequence: " + String(importError));
                }
            }

            receipt.sequence.imported = sequences.length > 0;
            receipt.duplicates.sequence = Math.max(0, sequences.length - 1);

            if (!sequences.length) {
                receipt.errors.push("Sequence not found or could not be imported: " + command.sequence_name);
                return JSON.stringify(receipt);
            }

            if (receipt.duplicates.sequence) {
                receipt.warnings.push("Multiple sequences with the same name exist; using the first one.");
            }

            // Open timeline
            if (command.requested_actions.open_timeline) {
                try {
                    app.project.openSequence(sequences[0].sequenceID);
                    var active = app.project.activeSequence;
                    receipt.sequence.timeline_open = !!active && String(active.sequenceID) === String(sequences[0].sequenceID);
                    if (!receipt.sequence.timeline_open) {
                        receipt.errors.push("Could not open sequence in Timeline.");
                    }
                } catch (timelineError) {
                    receipt.errors.push("Timeline error: " + String(timelineError));
                }
            }

            receipt.sequence.sequence_id = String(sequences[0].sequenceID || sequences[0].id || "unobserved");
            receipt.sequence.video_track_count = trackCount(sequences[0].videoTracks);
            receipt.sequence.audio_track_count = trackCount(sequences[0].audioTracks);

            // Handle render reference
            var targetBin = ensureBin(command.bin_name);
            var renderResult = importOne(command.files.render, targetBin);
            if (renderResult.item && command.render_reference_name) {
                try {
                    renderResult.item.name = command.render_reference_name;
                } catch (_) {}
            }

            receipt.render_reference.imported = !!renderResult.item;
            receipt.duplicates.render_reference = renderResult.duplicates;

            if (!renderResult.item) {
                var renderMsg = "Could not import rendered reference.";
                if (renderResult.error) renderMsg += " Reason: " + renderResult.error;
                receipt.errors.push(renderMsg);
            }

            receipt.render_reference.placed_on_editable_timeline = mediaOccurrencesOnTimeline(sequences[0], command.files.render) > 0;
            if (receipt.render_reference.placed_on_editable_timeline) {
                receipt.errors.push("Rendered reference is on the editable timeline (move it to the AI Render bin).");
            }

            // Handle captions
            var captionResult = importOne(command.files.captions, targetBin);
            receipt.captions.imported = !!captionResult.item;
            receipt.duplicates.captions = captionResult.duplicates;

            var captionApiAvailable = false;
            try {
                captionApiAvailable = typeof sequences[0].createCaptionTrack === "function";
            } catch (_) {}

            receipt.caption_api_available = captionApiAvailable;

            if (command.requested_actions.place_captions) {
                if (!captionResult.item) {
                    var captionMsg = "Could not import captions.";
                    if (captionResult.error) captionMsg += " Reason: " + captionResult.error;
                    receipt.errors.push(captionMsg);
                } else if (!captionApiAvailable) {
                    receipt.warnings.push("Caption track API not available; import SRT manually onto a Caption track.");
                } else {
                    try {
                        receipt.captions.track_created = !!sequences[0].createCaptionTrack(captionResult.item, 0);
                        receipt.captions.placed = receipt.captions.track_created;
                        if (!receipt.captions.track_created) {
                            receipt.warnings.push("Caption track creation returned no result; drag SRT to Caption track manually.");
                        }
                    } catch (captionError) {
                        receipt.errors.push("Caption track error: " + String(captionError));
                    }
                }
            } else {
                receipt.warnings.push("Caption track creation was skipped.");
            }

            // Handle music
            if (command.files.music && receipt.music) {
                var musicResult = importOne(command.files.music, targetBin);
                receipt.music.imported = !!musicResult.item;
                if (!musicResult.item) {
                    var musicMsg = "Could not import music file.";
                    if (musicResult.error) musicMsg += " Reason: " + musicResult.error;
                    receipt.warnings.push(musicMsg);
                } else {
                    receipt.music.placed_on_timeline = mediaOccurrencesOnTimeline(sequences[0], command.files.music) > 0;
                }
            }

            // Save project
            if (command.requested_actions.save_project) {
                try {
                    if (File) {
                        var savedFile = new File(command.expected_project_path);
                        var mtimeBefore = savedFile.exists ? savedFile.modified.getTime() : 0;
                        app.project.save();
                        receipt.project.active_path = app.project ? String(app.project.path) : "none";
                        receipt.project.saved = savedFile.exists && savedFile.modified.getTime() > mtimeBefore && normalize(receipt.project.active_path) === normalize(command.expected_project_path);
                        if (!receipt.project.saved) {
                            receipt.warnings.push("Project save result could not be verified.");
                        }
                    }
                } catch (saveError) {
                    receipt.errors.push("Could not save project: " + String(saveError));
                }
            }

        } catch (executionError) {
            receipt.errors.push("Execution error: " + String(executionError));
        }

        return JSON.stringify(receipt);
    };

}(AIRenderBridge));
