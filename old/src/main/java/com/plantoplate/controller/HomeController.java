package com.plantoplate.controller;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

/**
 * Root controller for handling web requests.
 */
@Controller
public class HomeController {

    /**
     * Handles incoming traffic to the root path (/) and serves the base layout frame.
     */
    @GetMapping("/")
    public String index() {
        return "index";
    }
}
