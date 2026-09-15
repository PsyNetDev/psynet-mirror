class AdditiveComplexTone {
  constructor(specs){
    this.num_harmonics = specs["num_harmonics"];
    this.max_num_harmonics = specs["max_num_harmonics"];
    this.attack = specs["attack"];
    this.decay = specs["decay"];
    this.release = specs["release"];
    this.sustain_amp = specs["sustain_amp"];
    this.type = "additive";

    console.assert(specs["num_harmonics"] <= specs["max_num_harmonics"], "Number of harmonics must not exceed max_num_harmonics=%d!",specs["max_num_harmonics"])

    if ("params" in specs) {
      console.assert(specs["max_num_harmonics"] - specs["params"]["amps"].length >= 0, "Length of custom timbre must not exceed %d!",specs["max_num_harmonics"])
      console.assert(specs["params"]["amps"].length == specs["params"]["freqs"].length, "Number of amplitudes must be equal to number of frequency partials!")

      this.amps = util.post_pad(specs["params"]["amps"], specs["max_num_harmonics"], 0);
      this.freqs = util.post_pad(specs["params"]["freqs"], specs["max_num_harmonics"], 0);
      this.octave_definition = 2;
      this.roll_off = undefined;
    } else {
      this.octave_definition = specs["octave_definition"];
      this.roll_off = specs["roll_off"];
      this.freqs = this.get_relative_freqs();
      this.amps = this.get_relative_amps();
    }
  }

  get_relative_freqs() {
    let freqs = []
    for (let i = 0; i < this.max_num_harmonics; i++) {
      freqs = freqs.concat(Math.pow(this.octave_definition, Math.log2(i + 1)))
    }
    return freqs
  }

  get_relative_amps() {
    let weights = util.complex(this.num_harmonics,this.roll_off);
    return util.post_pad(weights, this.max_num_harmonics,0)
  }
}

class HarmonicTone extends AdditiveComplexTone {
  constructor(specs){
    super(specs);
    this.octave_definition = 2;
    this.freqs = this.get_relative_freqs();
    this.amps = this.get_relative_amps();
    this.type = "harmonic";
  }
}

class StretchedTone extends AdditiveComplexTone {
  constructor(specs){
    super(specs);
    this.octave_definition = 2.1;
    this.freqs = this.get_relative_freqs();
    this.amps = this.get_relative_amps();
    this.type = "stretched";
  }
}

class CompressedTone extends AdditiveComplexTone {
  constructor(specs){
    super(specs);
    this.octave_definition = 1.9;
    this.freqs = this.get_relative_freqs();
    this.amps = this.get_relative_amps();
    this.type = "compressed";
  }
}

class PureTone extends AdditiveComplexTone {
  constructor(specs){
    super(specs);
    this.octave_definition = 2;
    this.freqs = this.get_relative_freqs();
    this.amps = this.get_relative_amps();
    this.type = "pure";
  }

  get_relative_amps() {
    let weights = util.complex(this.num_harmonics, this.roll_off);
    return util.post_pad([weights[0]], this.max_num_harmonics, 0)
  }
}

class BonangTone extends AdditiveComplexTone {
  constructor(specs){
    super(specs);
    this.octave_definition = 2;
    this.freqs = this.get_relative_freqs();
    this.upper_freqs = this.get_upper_relative_freqs();
    this.amps = this.get_relative_amps();
    this.type = "bonang";
  }

  get_upper_relative_freqs() {
    let freqs = [1,1.52,3.46,3.92]
    freqs = freqs.concat(new Array(this.max_num_harmonics - 4).fill(1))
    return freqs
  }

  get_relative_amps() {
    let weights = util.post_pad([], this.max_num_harmonics,0);
    for (let n = 0; n < 4; n++) {
      weights[n] = 1
    }
    return weights
  }
}

const ADDITIVE_TYPES = {
  "additive": AdditiveComplexTone,
  "harmonic": HarmonicTone,
  "stretched": StretchedTone,
  "compressed": CompressedTone,
  "pure": PureTone,
  "bonang": BonangTone
}

var ACTIVE_TONE_PARTS = typeof ACTIVE_TONE_PARTS !== "undefined" ? ACTIVE_TONE_PARTS : [];
var JS_SYNTH_PLAYBACK_GENERATION = typeof JS_SYNTH_PLAYBACK_GENERATION !== "undefined" ? JS_SYNTH_PLAYBACK_GENERATION : 0;

play_stimulus = function (stimulus) {
  note_list = stimulus["notes"]
  var n = note_list.length;
  var onsets = new Array(n).fill(0);
  var note_events = []

  cancel_scheduled_tonejs_audio()
  JS_SYNTH_PLAYBACK_GENERATION += 1
  const playback_generation = JS_SYNTH_PLAYBACK_GENERATION
  const active_nodes = ACTIVE_NODES
  const default_params = {...DEFAULT_PARAMS}
  const loaded_instruments = {...LOADED_INSTRUMENTS}

  Tone.Transport.cancel()
  Tone.Transport.stop()

  for (i = 0; i < n; i ++) {
    note = note_list[i];
    note_events = note_events.concat([{time: note.onset, note: note_list[i]}])
  }

  const part = new Tone.Part(((time, value) => {
    if (playback_generation !== JS_SYNTH_PLAYBACK_GENERATION) {
      return;
    }
    play_note(active_nodes, stimulus, value.note, 0.1 + time, default_params, loaded_instruments);
  }), note_events).start(0);
  ACTIVE_TONE_PARTS.push(part)

  Tone.Transport.start("+0.1");
}

play_note = function (active_nodes, stimulus, note_dict, time, default_params = DEFAULT_PARAMS, loaded_instruments = LOADED_INSTRUMENTS) {
    let note = {...note_dict};
    let pitches = note["pitches"];
    let pan = note["pan"];
    let N = pitches.length;
    let specs = {...stimulus["channels"][note["channel"]]["synth"]};
    let duration = note["duration"];
    let volume = note["volume"];

    for (key in default_params) {
      if (!(key in specs)){
        specs[key] = default_params[key]
      }
    }

    console.assert(N <= specs["max_num_pitches"], "Number of pitches in a chord must not exceed max_num_pitches=%d!",specs["max_num_pitches"])
    console.assert(specs["num_octave_transpositions"] <= specs["max_num_octave_transpositions"], "Number of transpositions must not exceed max_num_octave_transpositions=%d!",specs["max_num_octave_transpositions"])

    freqs = []
    for (i=0;i<N;i++){
      freqs = freqs.concat([util.midi2freq(pitches[i])])
    }

    if (specs["type"] in ADDITIVE_TYPES) {
      let synthesizer = new ADDITIVE_TYPES[specs["type"]](specs)
      freqs = util.post_pad(freqs, specs["max_num_pitches"], 0) // 0 frequency signifies no output
      custom_timbre_synth(active_nodes, freqs, synthesizer, specs, time, duration, pan, volume)
    } else if (Object.keys(loaded_instruments).includes(specs["type"])) {
      let instrument = loaded_instruments[specs["type"]]
      instrument.triggerAttackRelease(freqs, duration, time, volume)
    } else {
      throw {name : "NotImplementedError", message : "Timbre type not implemented!"};
    }

}

util_freq2midi = function (freq) {
    return Math.log2( freq / 440 ) * 12 + 69
}

util_midi2freq = function (midi) {
    return (Math.pow(2, (midi - 69) / 12)) * 440
}

util_complex = function (num_harmonics,roll_off) {
    var partials = []
    var norm = 0

    for (i=1;i<=num_harmonics;i++){
        weight = - Math.log2(i) * roll_off
        weight = Math.pow(10,weight/20)
        partials = partials.concat([weight])
        norm = norm + Math.pow(weight,2)
    }

    return partials.map(x => x/Math.sqrt(norm))

}

util_shepard = function (num_octave_transpositions,max_num_octave_transpositions,freq,octave_definition, default_params = DEFAULT_PARAMS) {
  var weights = []
  var norm = 0
  gamma = Math.log2(octave_definition) // inharmonic rescaling factor

  for (n=0;n<2*num_octave_transpositions+1;n++){
      curr_freq = util.freq2midi(freq * Math.pow(octave_definition,n - num_octave_transpositions))
      weight = util.gaussian(curr_freq, gamma * default_params["shepard_center"], gamma * default_params["shepard_width"]) // a Gaussian weight centered at the mid point of the midi scale, rescaled if needed for inharmonic compatability
      weights = weights.concat([weight])
      norm = norm + Math.pow(weight,2)
  }

  weights = weights.map(x => x/Math.sqrt(norm))

  padding = new Array(max_num_octave_transpositions-num_octave_transpositions).fill(0); // symmetric padding around the central weights to keep a fixed size
  weights = padding.concat(weights)
  weights = weights.concat(padding)

  return weights

}

util_gaussian = function(x,mu,sigma){
  N = Math.sqrt(2 * Math.PI * (sigma ** 2))
  return 1 / N * Math.exp(-1 * ((x - mu) ** 2) / (2 * sigma ** 2))
}

custom_timbre_synth = function(active_nodes,freqs,synth,specs,time,duration,pan,volume){
  var ampEnv = active_nodes["envelope"];
  ampEnv.attack = synth.attack;
  ampEnv.decay = synth.decay;
  ampEnv.sustain = synth.sustain_amp;
  ampEnv.release = synth.release;

  console.assert(synth.duration - synth.attack - synth.decay - synth.release >= 0, "The sum of attack, decay and release phases cannot exceed the full duration of the tone!")

  for (i = 0; i < specs["max_num_pitches"]; i++){
    freq = freqs[i]
    tone_nodes = active_nodes["complex_" + String(i)]

    if (freq == 0) {
      sweights = util.post_pad([], 2 * specs["max_num_octave_transpositions"] + 1, 0)
    } else {
      sweights = util.shepard(specs["num_octave_transpositions"], specs["max_num_octave_transpositions"], freq, synth.octave_definition, specs) // generate shepard weight tower around freq of width num_octave_transpositions, and then zero-pad to width max_num_octave_transpositions
    }

    for (j = 0; j < 2 * specs["max_num_octave_transpositions"] + 1; j++){
      curr_freq = freq * Math.pow(synth.octave_definition, j - specs["max_num_octave_transpositions"]); // generate Shepard octave compatible with stretching

      for (k = 0; k < specs["max_num_harmonics"]; k++) {
        osc = tone_nodes[j][k][0];
        gain = tone_nodes[j][k][1];

        if (synth.type == "bonang" && i>0) {
          osc.frequency.value = curr_freq * synth.upper_freqs[k];
        } else {
          osc.frequency.value = curr_freq * synth.freqs[k];
        }
        gain.gain.value = sweights[j] * synth.amps[k] ;

        if (volume) {
            gain.gain.value *= volume;
        }

        let panner = tone_nodes[j][k][2]
        if (pan[i]) {
          panner.pan.value = pan[i];
        } else {
          panner.pan.value = 0.0;
        }
      }
    }
  }
  ampEnv.triggerAttackRelease(duration - synth.release, time);
}

generate_additive_nodes = function(options){
  var control_nodes = {}
  var ampEnv = new Tone.AmplitudeEnvelope({
    "attackCurve" : DEFAULT_PARAMS["attackCurve"],
    "decayCurve": DEFAULT_PARAMS["decayCurve"],
    "releaseCurve" : DEFAULT_PARAMS["releaseCurve"]
  }).toDestination();

  for (i = 0; i < DEFAULT_PARAMS["max_num_pitches"]; i++){
    var tone_nodes = util.array(2 * DEFAULT_PARAMS["max_num_octave_transpositions"] + 1, DEFAULT_PARAMS["max_num_harmonics"])
    for (j = 0; j < 2 * DEFAULT_PARAMS["max_num_octave_transpositions"] + 1; j++){
      for (k = 0; k < DEFAULT_PARAMS["max_num_harmonics"]; k++){
        var osc = new Tone.Oscillator({"type": "sine", "volume": -17});
        var gain = new Tone.Gain();
        var panner = new Tone.Panner(0);
        osc.connect(gain).start();
        gain.connect(panner);
        panner.connect(ampEnv);
        tone_nodes[j][k] = [osc,gain,panner];
      }
    }
    control_nodes["complex_" + String(i)] = tone_nodes
  }

  control_nodes["envelope"] = ampEnv
  return control_nodes
}

util_2d_array = function(M,N) {
  var matrix = new Array(M)
  for (m=0;m<matrix.length;m++) {
    matrix[m] = new Array(N)
  }
  return matrix
}

load_sampler = async function (synth) {
    let sampler;

    return await new Promise((resolve) => {
        let spec = {
            onload: () => resolve(sampler.toDestination())
        };
        Object.assign(spec, INSTRUMENTS[synth]);
        sampler = new Tone.Sampler(spec);
    });
}

util_post_pad = function (vector, target_length, num) {
  console.assert(target_length - vector.length >= 0, "Invalid target length!")
  topad = new Array(target_length - vector.length).fill(num);
  padded_vector = vector.concat(topad)
  return padded_vector
}

util = {
  gaussian: util_gaussian,
  array: util_2d_array,
  complex: util_complex,
  freq2midi: util_freq2midi,
  midi2freq: util_midi2freq,
  shepard: util_shepard,
  post_pad: util_post_pad
}

function cancel_scheduled_tonejs_audio() {
    JS_SYNTH_PLAYBACK_GENERATION += 1;
    for (const part of ACTIVE_TONE_PARTS) {
        if (part && typeof part.dispose === "function") {
            part.dispose();
        }
    }
    ACTIVE_TONE_PARTS = [];
    if (typeof Tone !== 'undefined') {
        Tone.Transport.cancel();
        Tone.Transport.stop();
    }
}

function stop_all_tonejs_audio() {
    cancel_scheduled_tonejs_audio();
    // Stop custom timbre notes (ACTIVE_NODES)
    if (typeof ACTIVE_NODES !== "undefined") {
        const active_nodes = ACTIVE_NODES;
        if (active_nodes["envelope"] && typeof active_nodes["envelope"].triggerRelease === "function") {
            active_nodes["envelope"].triggerRelease();
        }
        for (const key in active_nodes) {
            if (!key.startsWith("complex_")) continue;
            const tone_nodes = active_nodes[key];
            for (const row of tone_nodes) {
                for (const cell of row) {
                    cell[1].gain.value = 0;
                }
            }
        }
    }
}
