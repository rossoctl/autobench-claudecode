Discarded 2026-09-08. OFF 1/2, ON 1/3 with the corrected placeholder-independent
verdict: no discrimination in either direction, and the same partial failure
appears with and without the skill. Measuring noise.

Cost: ON 1,277,763 tokens / 373s versus OFF 97,092 / 27s -- about 13x tokens and
14x wall, with no verdict improvement.

The rule ("left-align body; center only titles") is real, but without a title
placeholder there is no robust way to separate a legitimately centered title
from centered body copy; the shipped verdict approximates it with a <=24pt size
cutoff, which is too blunt to be a reliable discriminator.
