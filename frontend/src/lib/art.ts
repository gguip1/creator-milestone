// AI-generated sample art for the demo commission (design/assets/demo-art). It shows up only where
// the work it stands for is delivered or priced; it is evidence, not decoration.
export const ART = {
  sketch: { src: "/demo-art/sketch.png", alt: "Pencil sketch of the character: full body, short hair, round glasses, cropped jacket" },
  final: { src: "/demo-art/final.png", alt: "Finished color illustration of the character in a navy jacket" },
  hoodie: { src: "/demo-art/hoodie.png", alt: "The same character in a casual navy hoodie, the extra outfit" },
} as const;

/** The extra-outfit line of a change order, by its rate-card name or the client's words. */
export const isOutfit = (...texts: (string | null | undefined)[]): boolean =>
  /outfit|hoodie|costume/i.test(texts.filter(Boolean).join(" "));

/** Which sample image belongs to a milestone, by the plan's stage names. */
export function milestoneArt(title: string): keyof typeof ART | null {
  if (/sketch/i.test(title)) return "sketch";
  if (/final/i.test(title)) return "final";
  return null;
}
