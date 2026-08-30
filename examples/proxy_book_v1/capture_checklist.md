# BOOK-RIG 01 Capture Checklist

## Physical materials

- one book that can remain open;
- one yellow card labelled `MODULE A`;
- one paper arrow disk attached with a paper fastener;
- one outlined module holder on the left page;
- one green target pocket on the right page;
- one fixed square marker placed beside the book;
- one phone camera.

## Keep constant

- use the same table and room for the first baseline;
- keep the fixed marker stationary;
- capture the whole book plus marker;
- avoid hands covering the final state;
- save original images without filters.

## First capture session: 15 images

Take three clear images for each visible checkpoint:

1. initial closed state;
2. cover open, disk LEFT, module in holder;
3. disk UP;
4. module removed and holder empty;
5. module fully inside target slot.

For each checkpoint take:

- one front view;
- one left-oblique view;
- one right-oblique view.

Do not take training-scale data yet. These 15 images are only for checking
whether the manual, labels, prompt, and spatial output are coherent.

## Second capture session: error and uncertainty

After the first baseline works, add:

- disk between LEFT and UP;
- disk pointing DOWN;
- module partly in the holder;
- module partly in the target slot;
- wrong colored card in the target slot;
- target component occluded by a hand;
- blurred image;
- close crop that excludes the fixed marker.

Each should be labelled `wrong_operation` or `uncertain`, never `completed`.
