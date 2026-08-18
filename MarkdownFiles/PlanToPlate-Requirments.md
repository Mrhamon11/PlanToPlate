# PlanToPlate Web App

## High Level Goal:
I would like to build a web app that will run on a local server in my apartment. I will likely expose it to certain people via a tailscale node or by using a reverse proxy, but ultimately, the number of people who will use this app is very limited (likely between 10-20 maximum, and likely not all at the same time).


## MVP Functionality:
This app is to provide the following functions to users:
* Ability to store Recipes in a database.
  * A Recipe is defined as a list of ingredients (that can themselves also be recipes), measurements for each ingredient (should allow many kinds of units) followed by a list of cooking instructions.
  * In addition to Recipes, Ingredients should also be stored in the database (we should start with a bunch of common ones) with the ability for a user to add new ingredients that might not be there.
* Ability to create and manage RecipeBooks which contain Recipe objects. Users should be able to organize Recipes how they want (category, cuisine, alphabetically, etc), create however many RecipeBooks they want (and be able to name them), and store any number of Recipes (Recipes can be in multiple RecipeBooks at the same time).
* Ability to create "Dishes" which is a collection of recipes that constitute a full meal. 
* Ability to create lists of any kind (such as shopping lists, weekly meal planning lists, menu planning, etc). Lists can contain free form text, Recipes, or Dishes (or any combination of them).
* Ability to create a weekly meal plan (stored to a designated list) that allows users to manually or randomly select or create Dishes that represent the meal for a given day. Features include the following:
  * Clients should be able to supply parameters regarding what kinds of foods they want to eat that week and ensure that randomly selected Dishes respect that decision. For example, if a client only wants to each chicken one day a week, it should respect that. This needs to be flexible, yet the number of conditions/gears a client should be able to turn should be fleshed out early on to prevent decision fatigue.
  * Allow users to randomly select Recipes to construct a Dish. The app should be smart by allowing clients to select the kinds of foods they want their Dishes to be composed of, with a default of a Protein + Carb + Vegetable dish (salad, roasted veggie, raw veggie, etc). Alternatively, it could return an all in one/one pot meal as the dish.
  * Clients can decide how many days of the week the meal planner should generate meals for.
  * When the meal plan has been generated, all ingredients needed for each dish will be added to a designated/predefined shopping list (if none exist, the app should create one and call it "Shopping List").
* All database objects users can create (Ingredient, Recipe, RecipeBook, Dish, List) should have CRUD functionality for the user that created it. Note, commonly shared objects (such as predefined Ingredients or Recipes) as well as other user's objects should be read only (and even then, only if the user is permissioned to see it).
* All user defined objects should be shareable with other users. By default, each object should be defined as private, and users can permission other users in the system to read/use the object (such as in their lists, meal plans, recipes, etc), or they can make the object public. However, this should always be read only. A user with a read only copy is not allowed to share it (as they are not the owner). Only owners are allowed to share it.
* A user can make a copy of an object shared with them by another user, or of a default object. When they do that, the original object should be untouched, and a new object owned by them is created, giving them full CRUD access as if they created it from scratch. They should not be able to do this with private objects (as they would never be able to see them in the first place).
* All DB objects should have a "notes" section where users can add whatever notes they want independent of rest of the object properties.
* The app should be secure:
  * passwords salted and not saved as plain text
  * escaping sql injections (or other kinds of common exploits)
* Should allow users to login and logout (see below)


## Metrics and Properties:
* Dishes and Recipes should contain the following metrics and properties:
  * Rating (out of 5 stars)
  * Favorite (to allow users to search/group objects by favorite)
  * How many times the object was made by the user
  * A list of all users who have permission to see the object (only available to the owner)


## Login screen functionality:
* Users should be presented with the login screen when they first access the web page
* Users should enter their provided username, when prompted
* If a user is using a temp password, the login screen should prompt them to reset it and save that password (salted, not in plain text)
* If a user is logged in, they should be able to stay logged in until they click the logout button, even if they close the web browser (similar to how other apps keep users signed in)


## Admin controls and control center:
* There should be an admin control panel to allow admins to do the following:
  * Create users with a temp password (users should not be able to create their own accounts) that is shown to the admin so they can share
  * Delete users
  * See the DB tables directly rather than having to access the DB using another application
  * Create, read, update and delete entries in the DB for any table
  * Ability to mass import objects using JSON saved to a file.
  * Entitle a user account as an admin
  * Reset a user's password to a temp password for password resetting purposes
  * Admins should *not* be able to see an actual passwords (they should not be stored in plain text)


## Nice to haves:
* A recipe extractor that allows users to supply a link to an online recipe, and extract the recipe portion into a Recipe object. Users should be prompted to review and make edits if needed, and save the new Recipe to their Recipe DB. Perhaps an AI agent can be deployed on demand to crawl a website and extract the relevant recipe information, and add it to the user's Recipe database (using some API the agent will have access to) 
* Ability to add images to Recipes, Dishes, Lists, Ingredients and RecipeBooks via file upload
* Be optimized for mobile and desktop usage:
  * All windows should look good in either format
  * Ideally, all mouse based functionality should have an equivalent touch screen based function
* Have the ability to use the computer or phone camera to take pictures directly rather than forcing users to upload an image to a particular object.
* Create a "social" page that shows all entities users are sharing. The kinds of entities that can appear on the social tab include:
  * Raw:
    * Images
    * Text
  * DB Objects:
    * Recipes
    * Dishes 
    * Ingredients
    * RecipeBooks
  * Any combination of the above, including multiple of any kind of DB object or images
  * Posts should include a target audience (list of users, or public for all)
  * If a user is seeing a post containing a DB object, they should be able make a copy from that page (see copy rules above) as the post defined the audience field


## Tech Stack:
I would like to make this a python Django application. the app needs to have a REST API though for clients to connect to. I am using this as a learning experience to help teach me Django, but I will rely on AI quite a bit when I'm stuck, which is why I'd like to create plan files.
Here is are some suggestions for the tech stack, although I'd like to hear proposals from you. Please also include categories/components that are missing:
  * Framework: Django
  * DB: SQLite (as there will be very few users) although I'd like to have the option to switch to postgres at any time
  * Protocol: REST
  * Platforms: Web via mobile or desktop (no native android/iOS app for now, but should be designed so that one can quickly utilize what already exists)
  * Server: Local server (as there will be very few users), although I'd like to design this in a way where I can easily run this on an EC2 in AWS or on a VPS somewhere if needed.


### Request:
* I would like a detailed plan on how to execute the above. It should include technical details and should contain all relevant information a developer or an AI model would need to execute. It should be broken down into logic steps and tasks. 
* The code will primarily be written by me and claude code. However, I'd like to create a plan that can be executed as if an AI will write the whole thing. It will not be able to create this web app in one session. The files I need created are:
    * A milestones/living document that gives includes the project details, requirements, and any other context that would be good for an AI agent to read on each session to understand the project and what has been completed thus far.
    * 3 files per task that can be broken down into subtasks. The files include:
        * A design file that contains the design and implementation details for this task
        * A tasks file that contains the break down of the subtasks that comprise this task
        * A test plan file that contains all tests that need to be written and passing for the task to be considered complete.
        * The above three files hsould reference each other to give context to an AI
        * A requirement of this each task should be to read the milestones/living document when starting, and updating it when the task is complete. 
        * Add a new folder in the root of the project directory called "Plan". The milestones/living document should live there, and then you should create separate folders for each task. Inside those subfolders, the above three described plan files should be created.
* Create an CLAUDE.md that can be used as context for all prompts that does the following:
  * Never does anything dangerous without asking first (e.g. deleting files, modifying large amount of code, running database scripts, etc)
  * Never commits or pushes to git without my permission
  * Assumes the role of an expert python, Django, html, css and javascript developer
  * Assumes the role of an expert test creator (unit and integration)
  * Expert in SQLite Concurrency Safeguards, and can help optimize sql queries that are not managed by Django
  * Writes production ready code that is easy to read first, concise second
  * Doesn't add excess comments to code
  * Only lives in this project (i.e. don't update the global CLAUDE.md file)
* A series of agents/agent files that have the following personas and pipelines, and live only within this project:
    * Agents:
        * p2p-dev -> should be tasked with new development tasks (used whenever implement, develop, etc) is in the prompt. Should use sonnet 5 for the model.
        * p2p-tester -> should be tasked with running all tests and comparing the existing tests against the test plan file. Should use opus
        * p2p-reviewer -> should be tasked with reviewing the code that dev agent wrote. Needs to validate the tests make sense, the design is sound (and matches the plan files), and there are no bugs. Use opus for this agent.
    * Pipeline:
        * p2p-dev -> p2p-tester -> p2p-reviewer -> notify me to look at code and approve
        * If either p2p-tester or p2p-reviewer find issues, it should go back to p2p-dev to address and start the cycle again.
        * Multiple p2p-reviewers can be dispatched if needed.
* Before creating the plan  files, please ensure you understand this entire document, and provide suggestions where I requested them. If a decision I've made doesn't seem correct (e.g. it's not architecturally sound), please let me know and suggest something new.
* If you have any suggestions for other features, please let me know and we can talk it out. 
