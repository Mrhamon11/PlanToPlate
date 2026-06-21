# PlanToPlate Web App

### High Level Goal:
I would like to build a web app that will run on a local server in my apartment. I will likely expose it to certain people via a tailscale node or by using a reverse proxy, but ultimately, the number of people who will use this app is very limited (likely between 10-20 maximum, and likely not all at the same time).


### MVP Functionality:
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


### Metrics and Properties:
* Dishes and Recipes should contain the following metrics and properties:
  * Rating (out of 5 stars)
  * Favorite (to allow users to search/group objects by favorite)
  * How many times the object was made by the user
  * A list of all users who have permission to see the object


### Login screen functionality:
* Users should be presented with the login screen when they first access the web page
* Users should enter their provided username, when prompted
* If a user is using a temp password, the login screen should prompt them to reset it and save that password (salted, not in plain text)
* If a user is logged in, they should be able to stay logged in until they click the logout button, even if they close the web browser (similar to how other apps keep users signed in)


### Admin controls and control center:
* There should be an admin control panel to allow admins to do the following:
  * Create users with a temp password (users should not be able to create their own accounts) that is shown to the admin so they can share
  * Delete users
  * See the DB tables directly rather than having to access the DB using another application
  * Create, read, update and delete entries in the DB for any table
  * Ability to mass import objects using JSON saved to a file.
  * Entitle a user account as an admin
  * Reset a user's password to a temp password for password resetting purposes
  * Admins should *not* be able to see an actual passwords (they should not be stored in plain text)


### Nice to haves:
* A recipe extractor that allows users to supply a link to an online recipe, and extract the recipe portion into a Recipe object. Users should be prompted to review and make edits if needed, and save the new Recipe to their Recipe DB.
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


### Tech Stack:
I'm open to any suggestions. I primarily work in Java and am familiar with relational databases. However, I have never written a web app before. I know this can be done with spring boot, but I'm open to python or javascript/typescript frameworks (I prefer Java, then Python, then Javascript/Typescript). the app needs to have a REST API though for clients to connect to.

Here is are some suggestions for the tech stack, although I'd like to hear proposals from you. Please also include categories/components that are missing:
* Option 1:
  * Language: Java
  * Framework: Spring Boot + Vaadin
  * DB: SQLite (as there will be very few users)
  * Protocol: REST
  * Platforms: Web via mobile or desktop (no native android/iOS app for now, but should be designed so that one can quickly utilize what already exists)
  * Server: Local server (as there will be very few users)
* Option 2: 
  * Language: Python
  * Framework: Django
  * DB: SQLite (as there will be very few users)
  * Protocol: REST
  * Platforms: Web via mobile or desktop (no native android/iOS app for now, but should be designed so that one can quickly utilize what already exists)
  * Server: Local server (as there will be very few users)


### Request:
* I would like a detailed plan on how to execute the above. It should include technical details and should contain all relevant information a developer or an AI model would need to execute. It should be broken down into logic steps and tasks. 
* The code will primarily be written by a local AI model running qwen-3.5-9b with Q4_K_M with a context window of roughly 50k tokens using the Pi.dev agent. It will not be able to create this web app in one session, so in addition to an master PLAN.md file that contains all of the information to build this app, I would also like md files for each executable task that can be build by the local model. In an effort to reduce the amount of context needed when proceeding with later tasks, each task should create documentation of the API to give the model information about what has been created thus far without forcing it to read all of the code.
* If possible, create a skill that would be suitable for this model/agent to ensure they are as efficient as possible. 
* Before creating the plan md and skill files, please ensure you understand this entire document, and provide suggestions where I requested them. If a decision I've made doesn't seem correct (e.g. it's not architecturally sound), please let me know and suggest something new.
* As mentioned above, we need a list of common ingredients as a starting point that we can mass import into the DB (using the admin panel). Please include a file that contains this data, ideally JSON with whatever properties you decide an Ingredient should have.
* If you have any suggestions for other features, please let me know and we can talk it out. 