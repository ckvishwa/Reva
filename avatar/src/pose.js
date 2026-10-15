// One pose per session state, as small numbers in radians. The model has no animation clips yet
// (the owner's VRM and VRMA files arrive later, F0), so poses are procedural: the same keys are
// what clips will replace. Everything is gentle; nothing here depends on the model.
//
//   headPitch  + looks down        headYaw  + turns to the avatar's left     headRoll  + tilts
//   spineLean  + leans forward     sway     idle drift amount                breath    chest rise
//   lookUp     0..1, eyes up (thinking)

export const POSES = {
  idle: { headPitch: 0, headYaw: 0, headRoll: 0, spineLean: 0, sway: 0.03, breath: 0.012, lookUp: 0 },
  // Leaning in a little: she is listening.
  listening: { headPitch: 0.05, headYaw: 0, headRoll: 0.03, spineLean: 0.04, sway: 0.015, breath: 0.012, lookUp: 0 },
  // Head tilted, eyes up and to the side.
  thinking: { headPitch: -0.03, headYaw: 0.12, headRoll: 0.1, spineLean: 0, sway: 0.01, breath: 0.01, lookUp: 0.7 },
  // Upright and engaged; the nod is added from the mouth in the controller.
  speaking: { headPitch: 0.01, headYaw: 0, headRoll: 0, spineLean: 0.01, sway: 0.02, breath: 0.012, lookUp: 0 },
  // Still and attentive: a decision is waiting on the user.
  approval: { headPitch: 0.03, headYaw: 0, headRoll: 0, spineLean: 0.02, sway: 0, breath: 0.008, lookUp: 0 },
  // Head slightly down, very little motion.
  error: { headPitch: 0.14, headYaw: 0, headRoll: 0.02, spineLean: 0.02, sway: 0.004, breath: 0.008, lookUp: 0 },
};
