from Backend.database import connect_to_mongo, get_users_collection, close_mongo_connection
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()


async def main():
    await connect_to_mongo()
    users = get_users_collection()

    email = os.environ.get("DEBUG_EMAIL")
    if not email:
        email = input("Email to lookup: ")

    user = await users.find_one({"email": email})
    print("--- USER DOCUMENT ---")
    print(user)
    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
