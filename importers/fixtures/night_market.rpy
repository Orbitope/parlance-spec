# A small Ren'Py story for the importer tests. It carries the constructs that map
# (labels, say statements, menus, fall-through, `$` assignments of literals, an
# if/elif/else chain, [text] interpolation, staging statements) and a few that
# do not (call, a python block, a jump inside an if), so the declared-loss path
# is exercised rather than assumed.

define v = Character(_("Vendor"), color="#ffd080")
define config.menu_include_disabled = True

default coins = 2
default has_lamp = False
default stall = "the lantern stall"

init python:
    def haggle(n):
        return n - 1

label start:

    scene bg market
    with fade

    "The night market opens when the tide goes out."

    v "Welcome to [stall]. Mind the puddles — they are deeper than they look."

    menu:

        v "What will it be?"

        "Buy the lamp" if coins >= 2:
            $ coins -= 2
            $ has_lamp = True
            v "A good lamp. It will not go out in rain."

        "Ask about the tide":
            v "It turns at the second bell. Nobody sells after that."

        "Leave":
            jump leaving

    call haggle_scene

    if has_lamp:
        "The lamp swings from your hand, bright as a {i}coin{/i}."
    elif coins > 0:
        "You still have [coins] coins, and nothing to light the way."
    else:
        "Your pockets are empty and the path is dark."

    if coins == 0:
        jump leaving

    $ coins = 5

    show vendor smile at right

    v "Come back when the tide is out again. Say \"hello\" to the ferryman."

label leaving:

    play sound "bell.ogg"

    "A bell rings somewhere out on the flats.
     The stalls fold up one by one."

    return

label haggle_scene:

    v "You want it cheaper? Everyone does."

    return
