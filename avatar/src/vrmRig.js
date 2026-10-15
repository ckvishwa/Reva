// Draws controller frames onto a VRM model. This is the only file that touches the model; swapping
// the placeholder for the owner's model changes nothing else (F0 validates it first).

import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const REST_ARM = 1.15; // radians: arms hang at the sides instead of the T-pose

export async function loadVrm(url) {
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  const gltf = await loader.loadAsync(url);
  const vrm = gltf.userData.vrm;
  if (!vrm) throw new Error('the file is not a VRM model');
  VRMUtils.removeUnnecessaryVertices(gltf.scene);
  VRMUtils.combineSkeletons(gltf.scene);
  VRMUtils.rotateVRM0(vrm); // VRM 0.x models face the other way; a no-op for VRM 1.0
  vrm.scene.traverse((object) => {
    object.frustumCulled = false;
  });
  return vrm;
}

export class VrmRig {
  constructor(vrm) {
    this.vrm = vrm;
    const bone = (name) => vrm.humanoid?.getNormalizedBoneNode(name) ?? null;
    this.bones = {
      head: bone('head'),
      neck: bone('neck'),
      spine: bone('spine'),
      chest: bone('chest'),
      leftUpperArm: bone('leftUpperArm'),
      rightUpperArm: bone('rightUpperArm'),
    };
    this.expressions = vrm.expressionManager;
  }

  has(name) {
    return Boolean(this.expressions?.getExpression(name));
  }

  apply(frame, deltaSeconds) {
    const set = (name, value) => {
      if (this.expressions && this.has(name)) this.expressions.setValue(name, value);
    };
    for (const [name, weight] of Object.entries(frame.expression)) set(name, weight);
    // A blink should not fight a closed-eye face (happy, relaxed): scale it down as they close.
    set('blink', frame.blink * (1 - 0.7 * Math.max(frame.expression.happy, frame.expression.relaxed * 0.5)));
    for (const shape of ['aa', 'ih', 'ou', 'ee', 'oh']) set(shape, frame.mouth[shape]);
    set('lookUp', frame.lookUp * 0.6);

    const { head, neck, spine, chest, leftUpperArm, rightUpperArm } = this.bones;
    if (head) head.rotation.set(frame.head.x * 0.7, frame.head.y * 0.7, frame.head.z * 0.7);
    if (neck) neck.rotation.set(frame.head.x * 0.3, frame.head.y * 0.3, frame.head.z * 0.3);
    if (spine) spine.rotation.set(frame.spine.x, frame.spine.y, frame.spine.z);
    if (chest) chest.rotation.set(frame.chest.x, 0, 0);
    if (leftUpperArm) leftUpperArm.rotation.set(0, 0, -REST_ARM);
    if (rightUpperArm) rightUpperArm.rotation.set(0, 0, REST_ARM);
    this.vrm.update(deltaSeconds);
  }
}
