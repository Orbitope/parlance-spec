// ferry_landing.ink — the last boat has gone and the traveller has to decide what
// to do about it. Fixture for the ink-import skill: small, but it deliberately
// contains constructs Parlance cannot carry, so the declared-loss path is
// exercised rather than assumed.
# story: Ferry Landing

VAR paid_the_fare = false
VAR asked_about_road = false
VAR patience = 0
CONST FARE_IN_COINS = 2
LIST water_state = fine, rising, flood
EXTERNAL play_sound(name)

=== landing ===
# scene: dusk
Ferryman: The last boat went out at the bell, and the bell was an hour ago.
Ferryman: You can wait for the morning, or you can walk the long way round.
* [Ask what the fare would have been]
    Ferryman: Two coins, and a third when the water is high.
* [Ask about the long way round]
    ~ asked_about_road = true
    ~ patience = patience + 1
    Ferryman: Nine miles of mud, and a gate at the end of it that is also shut.
+ Say nothing at all
- -> landing.after

= after
{paid_the_fare: Ferryman: Your coin is in my hand and the boat is still gone.}
-> weather_note ->
Ferryman: You are still standing on my landing.
* {asked_about_road} [Ask whether the mud is passable]
    Ferryman: It is passable. That is not the same as advisable.
* [Offer the fare anyway]
    ~ paid_the_fare = true
    Ferryman: I will take it. I will still not row you across.
- -> bench

=== weather_note ===
Ferryman: The water came up all afternoon and has not gone down.
->->

=== rumours ===
Ferryman: They say the bridge upstream is out as well.

=== bench ===
The bench under the lamp is dry, which is the most that can be said for it. <>
{The lamp has been lit and left.|The lamp is still burning.}
<- rumours
Ferryman: Suit yourself. I am going in. # gruff
* [Wait for the morning]
    The ferryman goes in, and the door does not open again.
    ** [Sleep]
        You sleep badly and wake before the light.
    ** [Stay awake]
        You watch the water until the sky goes grey.
    -- -> morning
+ {bench > 1} [Look at the water again]
    Ferryman: Nothing has changed since you last looked.
- -> morning

=== morning ===
{ patience > 0:
    The night was long and you counted the hours of it.
- else:
    The night passed the way nights pass.
}
The boat comes back at first light with somebody else's cargo in it.
-> END
