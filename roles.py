import discord
from discord.ext import commands
import os

ROLE_NAMES = ["WOW", "B O N E R"]
INVITE_CODE = os.getenv("DISCORD_INVITE_CODE")
invite_uses = {}

async def setup_roles(bot):
    @bot.event
    async def on_member_join(member):
        global invite_uses
        print(f"New member joined: {member.name} in guild {member.guild.name}")
        guild = member.guild

        # Ensure invite tracking exists for this guild
        if guild.id not in invite_uses:
            invite_uses[guild.id] = {}
            print(f"Initialized invite tracking for guild: {guild.name}")

        # Fetch roles
        roles_to_add = []
        for role_name in ROLE_NAMES:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                roles_to_add.append(role)
            else:
                print(f"Error: Role '{role_name}' not found in guild {guild.name}.")

        # Check invite usage
        try:
            invites = await guild.invites()
            updated_uses = {invite.code: invite.uses for invite in invites}

            # Debug: Log invite usage differences
            for invite in invites:
                previous_uses = invite_uses[guild.id].get(invite.code, 0)
                print(f"Invite: {invite.code}, Previous uses: {previous_uses}, Current uses: {invite.uses}")

            # Determine which invite was used (usage increased by 1)
            used_invite = next(
                (invite for invite in invites if updated_uses[invite.code] == invite_uses[guild.id].get(invite.code, 0) + 1),
                None
            )

            # Update invite tracking
            invite_uses[guild.id] = updated_uses

            if used_invite:
                print(f"Invite used: {used_invite.code}")
                if used_invite.code == INVITE_CODE:
                    print("Correct invite detected. Proceeding to assign roles.")

                    # Assign roles
                    if roles_to_add:
                        try:
                            await member.add_roles(*roles_to_add)
                            role_names_str = ", ".join([role.name for role in roles_to_add])
                            print(f"Assigned roles '{role_names_str}' to {member.name}.")
                        except discord.Forbidden:
                            print("Error: Bot lacks permission to assign roles.")
                        except discord.HTTPException as e:
                            print(f"HTTPException occurred while assigning roles: {e}")
                else:
                    print(f"Incorrect invite used. Expected: {INVITE_CODE}, Got: {used_invite.code}")
            else:
                print("No invite detected with an increase in usage.")
        except discord.Forbidden:
            print(f"Error: Bot lacks permission to retrieve invites in guild {guild.name}.")
        except Exception as e:
            print(f"Unexpected error in on_member_join: {e}")