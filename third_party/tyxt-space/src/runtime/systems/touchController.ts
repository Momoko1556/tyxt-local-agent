import Phaser from 'phaser';

export function configureTouch(scene: Phaser.Scene): void {
  scene.input.addPointer(2);
  scene.input.setPollAlways();
}