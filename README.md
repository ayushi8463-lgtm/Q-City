# Q-City: Quantum Internet Tycoon

A strategy game about building a quantum network. You connect cities by setting up fiber links, building repeaters,
and delivering entangled pairs before they spoil. The local version runs its quantum steps as real Qiskit circuits
on the Qiskit Aer simulator, and can optionally use a measurement from a real IBM quantum computer.

## How to play

- **Goal:** earn $2,500. You lose if you miss 5 contracts or your cash drops below $0. You start with $500.
- **Links:** click a dashed route to set up a link. It is free, but links fail after a while (longer links fail sooner), and you set them up again.
- **Repeaters:** click a city to build one ($120). Every city in the middle of a route needs one.
- **Contracts:** each asks for a message between two cities with a minimum fidelity (pair quality, 0 to 1) and a deadline.
- **Delivery:** a contract is delivered only when every link on its route holds a pair at the same time, and the combined fidelity is high enough (at least 0.01 above the minimum). The pairs are then joined by the repeaters, and the message is teleported.
- **Pairs fade:** a stored pair loses fidelity over time and is thrown away below 0.70.
- **Upgrades:** longer memory, brighter source, and purification (cleaner pairs, made more slowly).
- **Upkeep and demand:** repeaters and upgrades cost money every second, and contracts get tougher every 150 seconds.

## Files

| File | What it is |
|---|---|
| `index.html` | The game (start, rules and map screens). Needs `server.py` running to use Qiskit. |
| `server.py` | FastAPI server that runs the Qiskit circuits and serves the game. |
| `run_on_ibm.py` | Optional script that runs a small circuit on real IBM hardware. |
| `requirements.txt` | Python packages. |

## Run it locally

1. Put all files in one folder and open a terminal there.
2. Install the packages:

       python -m pip install -r requirements.txt

3. Start the server:

       python -m uvicorn server:app --port 8000

4. Open **http://localhost:8000** in your browser (not the HTML file directly).

The text under the map should say **Qiskit backend live**. If it says "Backend offline", the game still works using built-in formulas.

## What runs in Qiskit

| Part | How it works |
|---|---|
| Link generation | Each link sends photons down its fiber. A photon is a qubit that passes through a lossy channel (amplitude damping, 0.2 dB per km), and one that arrives creates a pair. |
| Swap success | A Bell measurement succeeds only if both photons are detected. Each detector is a lossy channel (about 94.9% efficient, so 90% for the pair). |
| Swap fidelity | Bell pairs with noise matching their fidelity are joined by a Bell measurement and corrections, and the end pair is checked over 2,048 shots. |

Everything else is ordinary game code: pair decay, upgrades, link expiry, upkeep and deadlines.
The circuits are real Qiskit, run on a simulator with noise models defined in `server.py`. They do not run on quantum hardware.
The panels under the map show the circuits that ran.

## Run a piece on real IBM hardware (optional)

This runs two small circuits (a one-link check and a two-link swap) on an IBM quantum computer and uses the one-link result as the game's fresh-pair fidelity. It needs an IBM Quantum Platform account.

1. Create an account at IBM Quantum Platform and copy your API key.
2. Set your key in the terminal (keep it out of files you share):

       export QISKIT_IBM_TOKEN="your-api-key"

   If you have several instances, also set `QISKIT_IBM_INSTANCE` to the one you want.
3. Try a free dry run on a simulated IBM device:

       python run_on_ibm.py --fake

4. Run on real hardware (uses a few seconds of your QPU time; queue time varies):

       python run_on_ibm.py

   Add `--backend ibm_<name>` to pick a device. The default is the least busy one with enough qubits.
5. This saves `hardware_calibration.json`. Restart the server and reload the game.

Afterward, the "Fresh pair fidelity" box shows the measured value, and a checkbox under the map switches it on or off.
The value is kept between 0.85 and 0.99. The one-link circuit makes a pair and then undoes it, so it counts gate errors about twice and slightly underestimates real pair quality.

## Settings

Edit the constants at the top of `server.py`:

| Constant | Meaning | Default |
|---|---|---|
| `SHOTS` | Shots per swap-fidelity measurement | 2048 |
| `BSM_SUCCESS` | Target chance a Bell measurement works | 0.90 |
| `FIBER_DB_PER_KM` | Fiber loss | 0.2 |
| `MAX_GEN` | Most links simulated per tick | 8 |

## Troubleshooting

- **"Could not import module server":** you are in the wrong folder. Run `ls` and make sure `server.py` is there.
- **"Address already in use":** an old server is still running. Use `--port 8001` and open that address, or stop the old one with Ctrl+C in its window.
- **"Backend offline" in the game:** the page was not opened through the server. Use `http://localhost:8000`.
- **Packages installed but not found:** use `python -m pip` and `python -m uvicorn` so both use the same Python.
- **Old version shows after an update:** hard refresh with Cmd+Shift+R.

## Limits

- The quantum models (fiber loss, Werner-state noise, detector loss) are simplified standard models, not a full network simulation.
- Constants like 28 attempts per tick, 25 s memory time and 0.96 starting fidelity are tuned for gameplay.
- The hosted web version has no server, so it uses formulas instead of Qiskit.
