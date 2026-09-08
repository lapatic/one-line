storage={}; 

game={"name":"Dungeon Quest","hp":100,"gold":25,"potions":2}; 

status=(lambda: print(f"\nHP: {game['hp']} | Gold: {game['gold']} | Potions: {game['potions']}")); 

quit = (lambda: storage.update(quit=True)); 

fightstart = (lambda health, enemy: [x() for x in [
    (lambda: storage.update(enemy_hp=health)),
    (lambda: storage.update(fightend=False)),
    (lambda: print(f"\nA{'n' if list(enemy)[0] in ['a', 'e', 'i', 'o', 'u'] else ''} {enemy} attacks!"))
]]); 

fightactions = (lambda: [x()() for x in list([
(lambda: (lambda: list((
    storage.update(enemy_hp=storage["enemy_hp"]-10),
    game.update(hp=game["hp"]-5),
    print("You attack for 10 damage!"),
    print("The enemy hits you for 5 damage!", end=""),
    status()
    ) if (
        ((int(storage["fightchoice"])) == 1)
        ) else ((lambda: None),)))), 

(lambda: (lambda: list((
    game.update(hp=min(100, game["hp"] + 25)),
    game.update(potions=game["potions"]-1),
    print("You drink a potion!")
    ) if (
        ((int(storage["fightchoice"])) == 2)
        and (game["potions"] > 0)
        and ((sum([
        int((((int(storage["fightchoice"])) == 1))),
        ]) == 0))
        ) else ((lambda: None),)))), 

(lambda: (lambda: list((
    storage.update(fightend=True),
    storage.update(healthloss=__import__("math").ceil(__import__("random").random() * 30)),
    print(f"You escaped{', with some minor scratches' if storage['healthloss'] < 10 else (', but with some major wounds' if storage['healthloss'] > 20 else ', but got some minor wounds')}."),
    game.update(hp=game["hp"]-storage["healthloss"]),
    print(f"-{storage['healthloss']}HP")
    ) if (
        ((int(storage["fightchoice"])) == 3)
        and ((sum([
        int((((int(storage["fightchoice"])) == 1))),
        int((((int(storage["fightchoice"])) == 2))),
        ]) == 0))
        ) else ((lambda: None),)))), 

(lambda: (lambda: list((
    print("Invalid choice.")
    ) if (
        ((sum([
        int((((int(storage["fightchoice"])) == 1))),
        int((((int(storage["fightchoice"])) == 2))),
        int((((int(storage["fightchoice"])) == 3))),
        ]) == 0))
        ) else ((lambda: None),)))),
])]); 

fightend = (lambda enemy: [x()() for x in list((
    (lambda: (lambda: list((
        print("\nYou died!"),
        quit()
        ))) if (
            (game["hp"] <= 0)
            ) else (lambda: None)),
    (lambda: (lambda: list((
        ))) if (
            (storage["fightend"] == True)
            and (sum([
                int((game["hp"] <= 0))
            ]) == 0)
            ) else (lambda: None)),
    (lambda: (lambda: list((
        game.update(gold=game["gold"]+20),
        print(f"\nYou defeated the {enemy} and found 20 gold!")
        ))) if (sum([
            int((game["hp"] <= 0)),
            int((storage["fightend"] == True))
            ]) == 0) else (lambda: None)),
))]); 

fightwhileloop = lambda: list(
    iter(
        lambda: (
            (lambda: print(f"\nEnemy HP: {storage['enemy_hp']}"))(),
            (lambda: print("1. Attack"))(),
            (lambda: print("2. Use potion"))(),
            (lambda: print("3. Run"))(),
            (lambda: storage.update(fightchoice=input("> ")))(),
            (lambda: fightactions())(),
            ((storage["enemy_hp"] > 0) and (game["hp"] > 0) and (storage["fightend"] != True))
        )[-1],
        False
    )
); 

fight = (lambda enemy, health: [x() for x in [
    (lambda: fightstart(health, enemy)),
    (lambda: fightwhileloop()),
    (lambda: fightend(enemy)),
]]); 

treasurestart = (lambda: [x() for x in [
    (lambda: print("\nYou found a treasure chest!")),
]]); 

treasurechoice = (lambda: [x() for x in [
    (lambda: storage.update(treasurechoice=input("Open it? (y/n): "))),
]]); 

treasureactions = (lambda: [x()() for x in list([
(lambda: (lambda: list(((
    (lambda: [x()() for x in list((
    (lambda: (lambda: 
        storage.update(treasurerandom=__import__("random").random())
            )),
    (lambda: (lambda: list(((
        (lambda: [x()() for x in list((
        (lambda: (lambda: 
            storage.update(treasurerandom2=__import__("random").random())
                )),
        (lambda: (lambda: list((
            game.update(gold=game["gold"]+15),
            print("You found 15 gold!")
            ))) if (
                (storage["treasurerandom2"] <= 0.5)
                ) else (lambda: None)),
        (lambda: (lambda: list((
            game.update(potions=game["potions"]+1),
                        print("You found a healing potion!")
            ))) if (sum([
                int((storage["treasurerandom2"] <= 0.5))
                ]) == 0) else (lambda: None)),
        ))])())
        ) if (
            ((str(storage["treasurechoice"]).lower()) == "y")
            ) else ((lambda: None),)))), 
    (lambda: (lambda: list((
        print(f"\nIt was actually a mimic in disguise!"),
        fight("mimic", health=20)
        ))) if (sum([
            int((storage["treasurerandom"] <= 0.5))
            ]) == 0) else (lambda: None)),
    ))])())
    ) if (
        ((str(storage["treasurechoice"]).lower()) == "y")
        ) else ((lambda: None),)))), 

(lambda: (lambda: list((
    print("You leave the chest alone.")
    ) if (
        ((sum([
        int(((str(storage["treasurechoice"]).lower()) == "y")),
        ]) == 0))
        ) else ((lambda: None),)))),
])]); 

treasure = (lambda: [x() for x in [
    (lambda: treasurestart()),
    (lambda: treasurechoice()),
    (lambda: treasureactions()),
]]); 

mainactions = (lambda: [x()() for x in list([
(lambda: (lambda: list((
    status(),
    ) if (
        ((int(storage["mainchoice"])) == 1)
        ) else ((lambda: None),)))), 

(lambda: (lambda: list((
    fight(__import__("random").choice(["goblin", "octopus", "drunkard", "elf", "wizard"]), 10 * __import__("math").ceil(__import__("random").random() * 5)),
    ) if (
        ((int(storage["mainchoice"])) == 2)
        and ((sum([
        int((((int(storage["mainchoice"])) == 1))),
        ]) == 0))
        ) else ((lambda: None),)))), 

(lambda: (lambda: list((
    treasure(),
    ) if (
        ((int(storage["mainchoice"])) == 3)
        and ((sum([
        int((((int(storage["mainchoice"])) == 1))),
        int((((int(storage["mainchoice"])) == 2))),
        ]) == 0))
        ) else ((lambda: None),)))), 

(lambda: (lambda: list((
    quit(),
    ) if (
        ((int(storage["mainchoice"])) == 4)
        and ((sum([
        int((((int(storage["mainchoice"])) == 1))),
        int((((int(storage["mainchoice"])) == 2))),
        int((((int(storage["mainchoice"])) == 3))),
        ]) == 0))
        ) else ((lambda: None),)))),

(lambda: (lambda: list((
    print("Invalid choice."),
    ) if (
        ((sum([
        int((((int(storage["mainchoice"])) == 1))),
        int((((int(storage["mainchoice"])) == 2))),
        int((((int(storage["mainchoice"])) == 3))),
        int((((int(storage["mainchoice"])) == 4))),
        ]) == 0))
        ) else ((lambda: None),)))),
])]); 

gameloop = (lambda: list(
    iter(
        lambda: (
            (lambda: print("\n=== DUNGEON QUEST ==="))(),
            (lambda: print("1. Status"))(),
            (lambda: print("2. Fight"))(),
            (lambda: print("3. Treasure"))(),
            (lambda: print("4. Quit"))(),
            (lambda: storage.update(mainchoice=input("> ")))(),
            (lambda: mainactions())(),
            ((storage["quit"] != True))
        )[-1],
        False
    )
)); 

rungame = (lambda: list((
    storage.update(quit=False),
    gameloop(),
))); 

rungame(); 