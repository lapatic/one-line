import math
import random


game = {
    "name": "Dungeon Quest",
    "hp": 100,
    "gold": 25,
    "potions": 2,
    "room": 1
}


def status():
    print(
        f"\nHP: {game['hp']} | "
        f"Gold: {game['gold']} | "
        f"Potions: {game['potions']}"
    )


def fight(enemy, health):
    enemy_hp = health
    fight_ended = False

    article = "an" if enemy[0].lower() in "aeiou" else "a"
    print(f"\n{article} {enemy} attacks!")

    while enemy_hp > 0 and game["hp"] > 0 and not fight_ended:
        print(f"\nEnemy HP: {enemy_hp}")
        print("1. Attack")
        print("2. Use potion")
        print("3. Run")

        choice = input("> ")

        if choice == "1":
            enemy_hp -= 10
            game["hp"] -= 5

            print("You attack for 10 damage!")
            print("The enemy hits you for 5 damage!", end="")
            status()

        elif choice == "2" and game["potions"] > 0:
            game["hp"] = min(100, game["hp"] + 25)
            game["potions"] -= 1

            print("You drink a potion!")

        elif choice == "3":
            fight_ended = True

            health_loss = math.ceil(random.random() * 30)

            if health_loss < 10:
                message = "You escaped, with some minor scratches"
            elif health_loss > 20:
                message = "You escaped, but with some major wounds"
            else:
                message = "You escaped, but got some minor wounds"

            print(f"{message}.")
            game["hp"] -= health_loss
            print(f"-{health_loss}HP")

        else:
            print("Invalid choice.")

    if game["hp"] <= 0:
        print("\nYou died!")

    elif fight_ended:
        pass

    else:
        game["gold"] += 20

        print(
            f"\nYou defeated the {enemy} "
            f"and found 20 gold!"
        )


def treasure():
    print("\nYou found a treasure chest!")

    choice = input("Open it? (y/n): ")

    if choice.lower() == "y":

        treasure_random = random.random()

        # 50% chance of normal treasure
        if treasure_random <= 0.5:

            treasure_random_2 = random.random()

            # Gold
            if treasure_random_2 <= 0.5:
                game["gold"] += 15
                print("You found 15 gold!")

            # Potion
            else:
                game["potions"] += 1
                print("You found a healing potion!")

        # 50% chance of mimic
        else:
            print("\nIt was actually a mimic in disguise!")
            fight("mimic", health=20)

    else:
        print("You leave the chest alone.")


def main_actions(choice):

    if choice == "1":
        status()

    elif choice == "2":
        enemies = [
            "goblin",
            "octopus",
            "drunkard",
            "elf",
            "wizard"
        ]

        enemy = random.choice(enemies)

        health = (
            10 * math.ceil(random.random() * 5)
        )

        fight(enemy, health)

    elif choice == "3":
        treasure()

    elif choice == "4":
        print("Thanks for playing!")
        return True

    else:
        print("Invalid choice.")

    return False


def game_loop():

    quit_game = False

    while game["hp"] > 0 and not quit_game:

        print("\n=== DUNGEON QUEST ===")
        print("1. Status")
        print("2. Fight")
        print("3. Treasure")
        print("4. Quit")

        choice = input("> ")

        quit_game = main_actions(choice)


def run_game():
    game_loop()


run_game()