# TODO

## Modular design (Status: DONE)

right now, basically everything is in twilio_handler.py. That's not great. also is server.py even used? Before we implement anything complicated, we could stand to clean up around here.

We should have a modular design. There should be a TwilioHandler, sure, but the only thing the TwilioHandler does is handle Twilio stuff. Classes should have clear boundaries, unsurprising interfaces, and do one thing well. This is a relatively simple app right now, but this modularity, clear boundaries and separation of concerns should continue throughout the development lifecycle of the application.

## Outgoing calls (Status: DONE)

As a scheduling agent application, sending outgoing calls is a core feature. Currently we only accept incoming calls, and furthermore we conflate outgoing and incoming calls, which are fundamentally different. Think about it: if we are fielding an incoming call, it could be from anyone, so we'll need to know everything about the user and not have a very opinionated prompt. If we are making an outgoing call we know exactly who we are calling and why.

## Multiple prompts (Status: DONE)

we want to rely on canned prompts to allow the scheduling agent to function. Right now we just have a single prompt embedded in the instructions; instead, we should have the ability to select from multiple different prompts. For now, those can be simple examples: scheduling an appointment, or reserving a table at a restaurant. For incoming calls there still should be a canned prompt, but just a single example is fine for now.

## Encrypted user information file (Status: DONE)

We may need to handle sensitive information about the user to properly create reservations, like SSN. we also need less privileged, but still PII, information like name, date of birth, etc. Let's keep this in a central document that gets fed into every agent.

Security is top-of-mind with AI chatbots. As a first level of safety for users, let's encrypt their sensitive information in a yaml or json or some other config file. The program will then decrypt it while running with a secret supplied through the environment in some form or fashion.

## Google calendar integration (Status: DONE)

This application will be, at it's core, a scheduling application. It will benefit from many tools and integrations, but more than anything else, it will benefit from a google calendar integration. This integration would be used to create calendar events for the reservations / appointments created by the agent.

There is one catch, however: realtime agents do not persist beyond the call, and it's feasible that a call would end while an agent was calling the calendar tool to set the appointment. we'll have to capture the transcript of the call while the call is happening, then spin up a regular agent with the call transcript to actually make the calendar event. This represents a paradigm shift from single-agent to multi-agent orchestration in our application, so we must handle it carefully.

## MCP interface (Status: DONE, replaces texting integration)

The primary interface to the application is now an MCP server, which Claude (or any MCP-compatible client) can connect to. The MCP server exposes three tools: prepare_call (LLM-powered scenario selection + question generation), place_call (triggers the outgoing call), and get_call_outcome (polls for the post-call summary).

This replaces the earlier SMS-based orchestration approach.

## Runpod / Docker Container runtime (Status: DONE)

It would be nice to allow people to deploy this code in an isolated environment at the push of a button. to that end, it'd be great if we could have Docker container / runpod deployment capabilities.

Keep security in mind when designing this functionality - for instance, it would be in bad form to bake the user's information, even encrypted, into the image. That needs to be on a volume or something. Similarly the encryption secret should follow whatever best practices for secret injection there are for docker / runpod.

## Persistent memory (Status: TODO)

Imagine a scenario where we attempt to make an appointment, but are instead told we will receive a callback. It would be nice if there were persistent memory, such that when the callback was received, we have knowledge of (the summary of) the conversation, so we are better informed.

We should create a set of persistent memory tools that allow for getting and adding to memory. For now, they should be simple; there is a tool for querying the persistent memory that fetches the entire memory, and there's another tool that adds to that memory. We'll work on more complicated interfaces in the future