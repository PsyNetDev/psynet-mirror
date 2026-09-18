export async function activate({root, vars, psynet}) {
    const cfg = vars.shared_canvas_config;

    psynet.trial.onEvent("liveSessionInit", function () {
        const participantId = String(psynet.session.participant_id);
        const canvas = root.querySelector("#shared-canvas");
        const ctx = canvas.getContext("2d");
        const coinBonusEl = root.querySelector("#coin-bonus");
        let players = {};
        let coins = [];
        const pendingCollections = {};
        let collectedCoinIds = [];
        let keys = {};
        const arrowKeys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"];
        let own = {
            participant_id: participantId,
            label: "You",
            color: "#1f77b4",
            x: cfg.canvas_size / 2,
            y: cfg.canvas_size / 2,
            vx: 0,
            vy: 0,
            client_time: performance.now(),
            received_at: performance.now(),
        };
        let bonus = 0;
        let lastDrawAt = performance.now();
        let startedAt = null;
        let submitted = false;
        let gameStarted = false;
        const gameIntervalIds = [];

        function updateBonus(value) {
            bonus = Number(value || 0);
            coinBonusEl.textContent = bonus.toFixed(2);
            const performanceReward = document.getElementById("performance-reward");
            const totalReward = document.getElementById("total-reward");
            const rewardDetails = document.getElementById("reward-details");
            if (performanceReward) performanceReward.textContent = bonus.toFixed(2);
            if (totalReward) {
                const timeRewardEl = document.getElementById("time-reward");
                const timeReward = timeRewardEl
                    ? Number(timeRewardEl.textContent || 0)
                    : 0;
                totalReward.textContent = (timeReward + bonus).toFixed(2);
            }
            if (rewardDetails) rewardDetails.style.display = "";
        }

        function applySnapshot(msg) {
            const state = msg.state || msg;
            players = {};
            Object.keys(state.players || {}).forEach(function (playerId) {
                const player = state.players[playerId];
                players[String(playerId)] = Object.assign({}, player, {
                    received_at: performance.now(),
                });
            });
            if (players[participantId]) {
                own = Object.assign(own, players[participantId]);
            }
            coins = (state.coins || []).slice();
            collectedCoinIds = (state.collected_coins || [])
                .filter(function (collection) {
                    return String(collection.participant_id) === participantId;
                })
                .map(function (collection) {
                    return collection.coin_id;
                });
            updateBonus(collectedCoinIds.length * cfg.coin_bonus);
        }

        function applyPosition(update) {
            const updateParticipantId = String(update.participant_id);
            if (updateParticipantId === participantId) return;
            const existing =
                players[updateParticipantId] || (players[updateParticipantId] = {});
            Object.assign(existing, update);
            existing.received_at = performance.now();
        }

        function applyCollection(msg) {
            coins = (msg.coins || coins).filter(function (coin) {
                return coin.id !== msg.coin_id;
            });
            delete pendingCollections[msg.coin_id];
            if (String(msg.participant_id) === participantId) {
                collectedCoinIds.push(msg.coin_id);
                updateBonus(bonus + cfg.coin_bonus);
            }
        }

        function handleCollectRejected(msg) {
            delete pendingCollections[msg.coin_id];
        }

        function integrateOwnPlayer(now) {
            const dt = Math.min(0.08, (now - lastDrawAt) / 1000);
            const acceleration = 900;
            const friction = 0.90;
            const maxSpeed = 260;
            let ax = 0;
            let ay = 0;
            if (keys.ArrowLeft) ax -= acceleration;
            if (keys.ArrowRight) ax += acceleration;
            if (keys.ArrowUp) ay -= acceleration;
            if (keys.ArrowDown) ay += acceleration;
            own.vx = (Number(own.vx) || 0) + ax * dt;
            own.vy = (Number(own.vy) || 0) + ay * dt;
            if (!ax) own.vx *= friction;
            if (!ay) own.vy *= friction;
            const speed = Math.hypot(own.vx, own.vy);
            if (speed > maxSpeed) {
                own.vx = (own.vx / speed) * maxSpeed;
                own.vy = (own.vy / speed) * maxSpeed;
            }
            own.x = Math.max(
                cfg.player_radius,
                Math.min(cfg.canvas_size - cfg.player_radius, own.x + own.vx * dt),
            );
            own.y = Math.max(
                cfg.player_radius,
                Math.min(cfg.canvas_size - cfg.player_radius, own.y + own.vy * dt),
            );
            own.client_time = now;
            own.received_at = now;
            players[participantId] = own;
        }

        function drawPlayer(playerId, player, now) {
            const age = Math.min(160, now - (player.received_at || now)) / 1000;
            const x = Number(player.x || 0) + Number(player.vx || 0) * age;
            const y = Number(player.y || 0) + Number(player.vy || 0) * age;
            const isOwn = String(playerId) === participantId;
            ctx.beginPath();
            ctx.arc(x, y, cfg.player_radius, 0, Math.PI * 2);
            ctx.fillStyle = player.color || (isOwn ? "#1f77b4" : "#d62728");
            ctx.fill();
            ctx.lineWidth = isOwn ? 4 : 2;
            ctx.strokeStyle = isOwn ? "#111827" : "#ffffff";
            ctx.stroke();
        }

        function draw(now) {
            integrateOwnPlayer(now);
            ctx.clearRect(0, 0, cfg.canvas_size, cfg.canvas_size);
            ctx.fillStyle = "#f8fbff";
            ctx.fillRect(0, 0, cfg.canvas_size, cfg.canvas_size);
            ctx.strokeStyle = "#d8e2ef";
            ctx.lineWidth = 1;
            for (let grid = 80; grid < cfg.canvas_size; grid += 80) {
                ctx.beginPath();
                ctx.moveTo(grid, 0);
                ctx.lineTo(grid, 0 + cfg.canvas_size);
                ctx.moveTo(0, grid);
                ctx.lineTo(cfg.canvas_size, grid);
                ctx.stroke();
            }
            coins.forEach(function (coin) {
                ctx.beginPath();
                ctx.arc(coin.x, coin.y, coin.radius || cfg.coin_radius, 0, Math.PI * 2);
                ctx.fillStyle = "#f4c430";
                ctx.fill();
                ctx.strokeStyle = "#a27400";
                ctx.lineWidth = 2;
                ctx.stroke();
            });
            Object.keys(players).forEach(function (playerId) {
                drawPlayer(playerId, players[playerId], now);
            });
            checkCoinCollections();
            lastDrawAt = now;
        }

        function checkCoinCollections() {
            coins.forEach(function (coin) {
                if (pendingCollections[coin.id]) return;
                const distance = Math.hypot(
                    Number(coin.x) - own.x,
                    Number(coin.y) - own.y,
                );
                if (distance <= (coin.radius || cfg.coin_radius) + cfg.player_radius) {
                    pendingCollections[coin.id] = true;
                    psynet.websocket.send("collect", {
                        coin_id: coin.id,
                        x: own.x,
                        y: own.y,
                        client_time: performance.now(),
                    });
                }
            });
        }

        function sendPosition() {
            psynet.websocket.send("position", {
                x: own.x,
                y: own.y,
                vx: own.vx,
                vy: own.vy,
                client_time: performance.now(),
            });
        }

        function submitFinalAnswer() {
            if (submitted) return;
            submitted = true;
            psynet.nextPage({
                final_position: {x: own.x, y: own.y, vx: own.vx, vy: own.vy},
                n_collected_coins: collectedCoinIds.length,
            });
        }

        function focusCanvas() {
            if (document.activeElement !== canvas) {
                canvas.focus();
            }
        }

        function arrowKeyForEvent(event) {
            if (arrowKeys.indexOf(event.key) >= 0) return event.key;
            if (arrowKeys.indexOf(event.code) >= 0) return event.code;
            return null;
        }

        function isTextInput(target) {
            const tagName = target && target.tagName ? target.tagName.toLowerCase() : "";
            return (
                tagName === "input" ||
                tagName === "textarea" ||
                tagName === "select" ||
                Boolean(target && target.isContentEditable)
            );
        }

        function handleArrowKeyDown(event) {
            if (isTextInput(event.target)) return;
            const key = arrowKeyForEvent(event);
            if (!key) return;
            event.preventDefault();
            focusCanvas();
            const wasPressed = Boolean(keys[key]);
            keys[key] = true;
            if (!wasPressed) {
                draw(performance.now());
                sendPosition();
            }
        }

        function handleArrowKeyUp(event) {
            const key = arrowKeyForEvent(event);
            if (!key) return;
            keys[key] = false;
            event.preventDefault();
            sendPosition();
        }

        function handleWindowBlur() {
            keys = {};
        }

        function setGameInterval(handler, interval) {
            gameIntervalIds.push(setInterval(handler, interval));
        }

        psynet.addPageEventListener(canvas, "click", focusCanvas);
        psynet.addPageEventListener(window, "keydown", handleArrowKeyDown, true);
        psynet.addPageEventListener(window, "keyup", handleArrowKeyUp, true);
        psynet.addPageEventListener(window, "blur", handleWindowBlur);
        psynet.addPageCleanupCallback(function () {
            gameIntervalIds.forEach(clearInterval);
            gameIntervalIds.length = 0;
            keys = {};
        });
        focusCanvas();

        psynet.session.onFreshState(applySnapshot);
        psynet.session.onStarted(startGame);
        psynet.session.ready();

        psynet.websocket.handle("position_update", function (msg) {
            applyPosition(msg);
        });
        psynet.websocket.handle("coin_collected", function (msg) {
            applyCollection(msg);
        });
        psynet.websocket.handle("collect_rejected", function (msg) {
            handleCollectRejected(msg);
        });

        function startGame() {
            if (gameStarted) return;
            gameStarted = true;
            startedAt = performance.now();
            setGameInterval(function () {
                draw(performance.now());
            }, cfg.draw_interval_ms);
            setGameInterval(sendPosition, cfg.send_interval_ms);
            setGameInterval(function () {
                if (performance.now() - startedAt >= cfg.trial_seconds * 1000) {
                    submitFinalAnswer();
                }
            }, 200);
        }
    });
}
